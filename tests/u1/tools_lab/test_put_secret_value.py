"""Tests of tools/lab/rancher_host/put_secret_value.py (plan Step 11).

The script runs on the Rancher host at first boot and stores Rancher's generated
admin password in Secrets Manager (REQ-021.1). Here the instance metadata service
and Secrets Manager are a fake opener, so nothing leaves the test, and the
signature is checked against botocore's own Signature Version 4 signer.
"""

import datetime
import email.message
import io
import json
import secrets
import urllib.error
import urllib.request
from types import ModuleType
from typing import Any
from unittest import mock

import botocore.auth
import pytest
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials as BotoCredentials

# The name of the Secrets Manager secret the Rancher host writes (not a secret value).
ADMIN_CREDENTIAL_NAME = "sre-lab/rancher-admin-password"
ARGS = ["--secret-id", ADMIN_CREDENTIAL_NAME, "--region", "us-east-1"]


class FakeResponse:
    """A urllib response holding a fixed body."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def aws_error(code: int, error_type: str) -> urllib.error.HTTPError:
    """An error answer from Secrets Manager, with its JSON error type."""
    body = io.BytesIO(json.dumps({"__type": error_type, "message": "fake"}).encode())
    return urllib.error.HTTPError(
        "https://secretsmanager.us-east-1.amazonaws.com/",
        code,
        "fake",
        email.message.Message(),
        body,
    )


class FakeAws:
    """The instance metadata service and Secrets Manager, as one urllib opener."""

    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = failures or []
        self.requests: list[urllib.request.Request] = []
        self.stored: list[dict[str, Any]] = []
        self.credentials = {
            "AccessKeyId": "AKIDEXAMPLE",
            "SecretAccessKey": secrets.token_hex(20),
            "Token": secrets.token_hex(40),
        }

    def __call__(self, request: urllib.request.Request, timeout: float) -> FakeResponse:
        self.requests.append(request)
        url = request.full_url
        if url.endswith("/latest/api/token"):
            return FakeResponse(b"imds-session")
        if url.endswith("/iam/security-credentials/"):
            return FakeResponse(b"sre-lab-rancher-host\n")
        if url.endswith("/iam/security-credentials/sre-lab-rancher-host"):
            return FakeResponse(json.dumps(self.credentials).encode())
        assert url == "https://secretsmanager.us-east-1.amazonaws.com/"
        if self.failures:
            raise self.failures.pop(0)
        assert isinstance(request.data, bytes)
        self.stored.append(json.loads(request.data))
        return FakeResponse(b'{"VersionId": "fake"}')

    def secrets_manager_calls(self) -> list[urllib.request.Request]:
        return [r for r in self.requests if r.full_url.startswith("https://secretsmanager.")]


def test_req_021_signature_matches_botocore(put_secret_value: ModuleType) -> None:
    """REQ-021.1: the PutSecretValue call is signed exactly as botocore signs it.

    Same request, same credentials, same moment: the Authorization headers match.
    """
    credentials = put_secret_value.Credentials(
        "AKIDEXAMPLE", secrets.token_hex(20), secrets.token_hex(40)
    )
    url = "https://secretsmanager.us-east-1.amazonaws.com/"
    body = json.dumps(
        {"SecretId": ADMIN_CREDENTIAL_NAME, "SecretString": secrets.token_hex(8)}
    ).encode()
    headers = {
        "Content-Type": "application/x-amz-json-1.1",
        "X-Amz-Target": "secretsmanager.PutSecretValue",
    }
    moment = datetime.datetime(2026, 11, 11, 12, 30, 45, tzinfo=datetime.UTC)

    ours = put_secret_value.sign_request(
        url, headers, body, credentials, "us-east-1", moment.strftime("%Y%m%dT%H%M%SZ")
    )

    reference = AWSRequest(method="POST", url=url, data=body, headers=dict(headers))
    signer = botocore.auth.SigV4Auth(
        BotoCredentials(
            credentials.access_key_id, credentials.secret_access_key, credentials.session_token
        ),
        "secretsmanager",
        "us-east-1",
    )
    with mock.patch.object(botocore.auth, "get_current_datetime", return_value=moment):
        signer.add_auth(reference)
    assert ours["Authorization"] == reference.headers["Authorization"]
    assert ours["X-Amz-Date"] == reference.headers["X-Amz-Date"]
    assert ours["X-Amz-Security-Token"] == credentials.session_token


def test_req_021_stores_the_value_from_stdin_with_the_instance_role(
    put_secret_value: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-021.1: the value read from stdin becomes the secret's current version.

    The credentials come from IMDSv2 (a session first, then the role), the call
    is one signed PutSecretValue, and the value is never printed.
    """
    value = secrets.token_urlsafe(40)
    aws = FakeAws()

    status = put_secret_value.main(ARGS, stdin=io.StringIO(value), opener=aws, sleep=lambda _: None)

    assert status == 0
    assert [item["SecretString"] for item in aws.stored] == [value]
    assert aws.stored[0]["SecretId"] == ADMIN_CREDENTIAL_NAME
    assert aws.stored[0]["ClientRequestToken"]
    session_request = aws.requests[0]
    assert session_request.get_method() == "PUT"
    assert session_request.get_header("X-aws-ec2-metadata-token-ttl-seconds") == "300"
    assert all(
        r.get_header("X-aws-ec2-metadata-token") == "imds-session" for r in aws.requests[1:3]
    )
    call = aws.secrets_manager_calls()[0]
    assert call.get_header("X-amz-target") == "secretsmanager.PutSecretValue"
    assert call.get_header("Authorization", "").startswith(
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/"
    )
    out, err = capsys.readouterr()
    assert value not in out + err


def test_req_021_retries_throttling_and_server_errors_then_succeeds(
    put_secret_value: ModuleType,
) -> None:
    """REQ-021.1: a throttled or failing Secrets Manager does not lose the password.

    Throttling and 5xx answers are retried with growing waits until one succeeds.
    """
    value = secrets.token_urlsafe(40)
    aws = FakeAws([aws_error(400, "ThrottlingException"), aws_error(503, "InternalServiceError")])
    waits: list[float] = []

    status = put_secret_value.main(ARGS, stdin=io.StringIO(value), opener=aws, sleep=waits.append)

    assert status == 0
    assert waits == [2, 4]
    assert len(aws.secrets_manager_calls()) == 3
    assert [item["SecretString"] for item in aws.stored] == [value]


def test_req_021_access_denied_fails_at_once_without_the_value_in_the_message(
    put_secret_value: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-021.1: a refused write stops at once, names the error, and hides the value."""
    value = secrets.token_urlsafe(40)
    aws = FakeAws([aws_error(400, "AccessDeniedException")])
    waits: list[float] = []

    status = put_secret_value.main(ARGS, stdin=io.StringIO(value), opener=aws, sleep=waits.append)

    assert status == 1
    assert waits == []
    out, err = capsys.readouterr()
    assert "AccessDeniedException" in err
    assert value not in out + err


def test_req_021_network_errors_are_retried_then_reported(put_secret_value: ModuleType) -> None:
    """REQ-021.1: an unreachable Secrets Manager is retried five times, then reported."""
    aws = FakeAws([urllib.error.URLError("unreachable") for _ in range(5)])
    waits: list[float] = []

    status = put_secret_value.main(
        ARGS, stdin=io.StringIO(secrets.token_hex(8)), opener=aws, sleep=waits.append
    )

    assert status == 1
    assert waits == [2, 4, 8, 16]
    assert aws.stored == []


def test_req_021_empty_input_stores_nothing(
    put_secret_value: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """REQ-021.1: an empty password is never stored: the script stops before any call."""
    aws = FakeAws()

    status = put_secret_value.main(ARGS, stdin=io.StringIO(""), opener=aws, sleep=lambda _: None)

    assert status == 2
    assert aws.requests == []
    assert "standard input is empty" in capsys.readouterr().err


def test_req_021_only_imds_and_secrets_manager_are_contacted(put_secret_value: ModuleType) -> None:
    """REQ-021.1: the script refuses any other address, so no file: or other URL is opened."""
    with pytest.raises(put_secret_value.PutSecretError, match="refusing to contact"):
        put_secret_value.build_request("file:///etc/passwd", {})
    with pytest.raises(put_secret_value.PutSecretError, match="refusing to contact"):
        put_secret_value.build_request("https://example.com/", {})
    allowed = put_secret_value.build_request("https://secretsmanager.us-east-1.amazonaws.com/", {})
    assert allowed.full_url == "https://secretsmanager.us-east-1.amazonaws.com/"
