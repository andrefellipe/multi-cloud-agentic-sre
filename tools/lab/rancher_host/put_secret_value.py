#!/usr/bin/env python3
"""Write the value on standard input to one Secrets Manager secret (REQ-021.1).

The Rancher host (LC17) runs this once, at first boot, from the user data in
``infra/aws/lab/templates/rancher-host-user-data.sh.tftpl``. It stores the admin
password that Rancher generated, so the password exists only in Rancher and in
Secrets Manager, never in Terraform. The Ubuntu image has no AWS CLI, so this
script uses only the Python standard library: the instance role's credentials
from IMDSv2, and one ``PutSecretValue`` call signed with Signature Version 4.

The value is read from standard input, never from arguments, and never appears
in output or in error messages.

Usage:
    printf '%s' "$value" | python3 put_secret_value.py --secret-id NAME --region REGION

Exit status: 0 when the value is stored, 1 when it is not, 2 on a usage error.
"""

import argparse
import datetime
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import IO, Protocol

IMDS_BASE = "http://169.254.169.254/latest"
IMDS_SESSION_TTL_SECONDS = "300"
SERVICE = "secretsmanager"
# The only addresses this script talks to: the instance metadata service and Secrets Manager.
ALLOWED_URL_PREFIXES = (f"{IMDS_BASE}/", "https://secretsmanager.")
ATTEMPTS = 5
# Error types worth retrying besides any 5xx answer: AWS asking the caller to slow down.
RETRYABLE_ERROR_TYPES = frozenset({"ThrottlingException", "TooManyRequestsException"})


class Response(Protocol):
    """The part of an HTTP response this script uses."""

    def read(self) -> bytes: ...

    def __enter__(self) -> "Response": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


Opener = Callable[[urllib.request.Request, float], Response]


class PutSecretError(Exception):
    """The value could not be stored. The message never contains the value."""


@dataclass(frozen=True)
class Credentials:
    """Temporary AWS credentials of the instance role."""

    access_key_id: str
    secret_access_key: str
    session_token: str


def build_request(
    url: str,
    headers: Mapping[str, str],
    data: bytes | None = None,
    method: str = "GET",
) -> urllib.request.Request:
    """Return a request for ``url``, refusing any address other than IMDS and Secrets Manager.

    The check is why urllib's file: and custom schemes can never be reached here.
    """
    if not url.startswith(ALLOWED_URL_PREFIXES):
        raise PutSecretError(f"refusing to contact {url}")
    return urllib.request.Request(url, data=data, method=method, headers=dict(headers))  # noqa: S310


def default_opener(request: urllib.request.Request, timeout: float) -> Response:
    """Open ``request`` with urllib, which raises HTTPError for 4xx and 5xx answers."""
    response: Response = urllib.request.urlopen(request, timeout=timeout)  # noqa: S310
    return response


def fetch_instance_credentials(opener: Opener) -> Credentials:
    """Return the instance role's credentials from the instance metadata service (IMDSv2)."""
    token_request = build_request(
        f"{IMDS_BASE}/api/token",
        {"X-aws-ec2-metadata-token-ttl-seconds": IMDS_SESSION_TTL_SECONDS},
        data=b"",
        method="PUT",
    )
    with opener(token_request, 5) as response:
        session = response.read().decode()
    headers = {"X-aws-ec2-metadata-token": session}
    roles_url = f"{IMDS_BASE}/meta-data/iam/security-credentials/"
    with opener(build_request(roles_url, headers), 5) as response:
        roles = response.read().decode().split()
    if not roles:
        raise PutSecretError("the instance has no IAM role")
    with opener(build_request(roles_url + roles[0], headers), 5) as response:
        payload = response.read()
    try:
        document = json.loads(payload)
        return Credentials(
            access_key_id=document["AccessKeyId"],
            secret_access_key=document["SecretAccessKey"],
            session_token=document["Token"],
        )
    except (ValueError, KeyError, TypeError) as error:
        raise PutSecretError("the instance role's credentials are unreadable") from error


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def sign_request(
    url: str,
    headers: Mapping[str, str],
    body: bytes,
    credentials: Credentials,
    region: str,
    amz_date: str,
) -> dict[str, str]:
    """Return ``headers`` plus the Signature Version 4 headers for a POST of ``body`` to ``url``.

    ``amz_date`` is the request time as ``YYYYMMDDTHHMMSSZ``. Every header given
    is signed, together with the host, the date and the session token.
    """
    signed = {name.lower(): " ".join(value.split()) for name, value in headers.items()}
    signed.update(
        {
            "host": urllib.parse.urlsplit(url).netloc,
            "x-amz-date": amz_date,
            "x-amz-security-token": credentials.session_token,
        }
    )
    names = sorted(signed)
    canonical_request = "\n".join(
        [
            "POST",
            urllib.parse.urlsplit(url).path or "/",
            "",
            "".join(f"{name}:{signed[name]}\n" for name in names),
            ";".join(names),
            hashlib.sha256(body).hexdigest(),
        ]
    )
    scope = f"{amz_date[:8]}/{region}/{SERVICE}/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = _hmac(f"AWS4{credentials.secret_access_key}".encode(), amz_date[:8])
    for part in (region, SERVICE, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        **headers,
        "X-Amz-Date": amz_date,
        "X-Amz-Security-Token": credentials.session_token,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={credentials.access_key_id}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={signature}"
        ),
    }


def _error_type(error: urllib.error.HTTPError) -> str:
    """Return the AWS error type of an error answer, such as ``AccessDeniedException``."""
    try:
        payload = json.loads(error.read() or b"{}")
    except ValueError:
        return "UnreadableError"
    raw = str(payload.get("__type", "")) if isinstance(payload, dict) else ""
    return raw.rsplit("#", 1)[-1] or "UnknownError"


def _send_once(
    secret_id: str,
    value: str,
    region: str,
    credentials: Credentials,
    opener: Opener,
    now: Callable[[], datetime.datetime],
) -> None:
    url = f"https://secretsmanager.{region}.amazonaws.com/"
    body = json.dumps(
        {"SecretId": secret_id, "SecretString": value, "ClientRequestToken": str(uuid.uuid4())}
    ).encode()
    headers = sign_request(
        url,
        {
            "Content-Type": "application/x-amz-json-1.1",
            "X-Amz-Target": "secretsmanager.PutSecretValue",
        },
        body,
        credentials,
        region,
        now().strftime("%Y%m%dT%H%M%SZ"),
    )
    request = build_request(url, headers, data=body, method="POST")
    with opener(request, 10) as response:
        response.read()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def put_secret_value(
    secret_id: str,
    value: str,
    region: str,
    opener: Opener = default_opener,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime.datetime] = _utc_now,
) -> None:
    """Store ``value`` as the current version of ``secret_id``.

    Network errors, throttling and 5xx answers are retried, up to ATTEMPTS
    attempts with capped backoff. Any other error stops at once.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            credentials = fetch_instance_credentials(opener)
            _send_once(secret_id, value, region, credentials, opener, now)
            return
        except urllib.error.HTTPError as error:
            error_type = _error_type(error)
            retryable = error.code >= 500 or error_type in RETRYABLE_ERROR_TYPES
            reason = f"HTTP {error.code} {error_type}"
        except OSError as error:  # URLError, timeouts and socket errors
            retryable, reason = True, type(error).__name__
        if not retryable or attempt == ATTEMPTS:
            raise PutSecretError(f"PutSecretValue on {secret_id} failed: {reason}")
        print(f"put_secret_value: attempt {attempt} failed ({reason}); retrying.", file=sys.stderr)
        sleep(min(2**attempt, 20))


def main(
    argv: Sequence[str] | None = None,
    stdin: IO[str] | None = None,
    opener: Opener = default_opener,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Read the value from standard input, store it, and return the exit status."""
    parser = argparse.ArgumentParser(
        description="Write standard input to a Secrets Manager secret."
    )
    parser.add_argument("--secret-id", required=True, help="secret name or ARN")
    parser.add_argument("--region", required=True, help="AWS Region of the secret")
    args = parser.parse_args(argv)
    value = (stdin or sys.stdin).read()
    if not value:
        print("put_secret_value: standard input is empty; nothing stored.", file=sys.stderr)
        return 2
    try:
        put_secret_value(args.secret_id, value, args.region, opener=opener, sleep=sleep)
    except PutSecretError as error:
        print(f"put_secret_value: {error}", file=sys.stderr)
        return 1
    print(f"put_secret_value: stored a new version of {args.secret_id}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
