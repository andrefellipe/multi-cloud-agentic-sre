#!/usr/bin/env python3
"""Spike A, steps A2 and A3: prepare the spike's Rancher for the agent's read-only test.

Run it in your admin terminal, from the repository root, once A1's instance runs:

    uv run python tools/spikes/spike-a/configure_spike_rancher.py <public IPv4 of rancher-spike>

It reuses tools/lab/configure_rancher.py, whose Rancher calls were checked against
Rancher 2.15.3 in the lab. In order, it:

1. waits until Rancher has finished starting, which /cacerts serving its CA shows
   (up to 20 minutes; /ping answers minutes earlier);
2. saves Rancher's self-signed CA to ~/.rancher-spike/rancher-ca.pem and from then
   on trusts only that CA. The host name is not checked, because the certificate
   cannot name the instance's public IP;
3. signs in as admin. If an earlier run stored an admin password in your Keychain,
   it uses that. Otherwise it reads the generated bootstrap password from the
   container's log over SSH, signs in with it, and replaces it with a new random
   password;
4. sets Rancher's server URL to https://<ip>;
5. creates the agent-readonly cluster role (get, list and watch on pods, pod logs,
   events, namespaces, deployments, replica sets, services and nodes; nothing on
   Secrets), and the sre-agent user with login access only, and binds that user
   to the local cluster with that role;
6. signs in as sre-agent, issues its API token with a 1-day expiry, proves that the
   token signs in, and deletes the tokens that earlier runs issued.

The admin password, the sre-agent password and the token go to your login Keychain,
service "rancher-spike", accounts "admin", "sre-agent" and "sre-agent-token". The
script never prints them. Running it again is safe: it signs in with the stored
admin password, gives sre-agent a new password and a new token, and changes nothing
else.

Exit status: 0 when the spike's Rancher is ready, 1 when a step fails, 2 on a usage
error.
"""

from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import re
import secrets
import ssl
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
KEYCHAIN_SERVICE = "rancher-spike"
ADMIN = "admin"
AGENT_USERNAME = "sre-agent"
AGENT_TOKEN_ACCOUNT = "sre-agent-token"  # noqa: S105 - a Keychain account name
ROLE_TEMPLATE = "agent-readonly"
LOCAL_CLUSTER = "local"
TOKEN_DESCRIPTION = (
    "sre-agent spike token, issued by tools/spikes/spike-a/configure_spike_rancher.py"  # noqa: S105
)
BOOTSTRAP_LINE = re.compile(r"Bootstrap Password: (\S+)")
# How tools/lab/configure_rancher.py words a sign-in that Rancher answered with 5xx.
SERVER_ERROR = re.compile(r"\(HTTP 5\d\d\)$")
# macOS paths, so that no other program of the same name runs.
SECURITY = "/usr/bin/security"
SSH = "/usr/bin/ssh"


def _load_lab_script() -> ModuleType:
    """Load tools/lab/configure_rancher.py: tools/lab/ is a script folder, not a package."""
    path = REPO_ROOT / "tools" / "lab" / "configure_rancher.py"
    spec = importlib.util.spec_from_file_location("configure_rancher", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cr = _load_lab_script()
JSON = dict[str, Any]


class Keychain(Protocol):
    def get(self, account: str) -> str | None: ...

    def put(self, account: str, secret: str) -> None: ...


class MacKeychain:
    """The login Keychain, through macOS's ``security`` tool."""

    def get(self, account: str) -> str | None:
        result = subprocess.run(  # noqa: S603 - fixed program and arguments
            [SECURITY, "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
            capture_output=True,
            text=True,
            check=False,
        )
        value = result.stdout.rstrip("\n")
        return value if result.returncode == 0 and value else None

    def put(self, account: str, secret: str) -> None:
        result = subprocess.run(  # noqa: S603 - fixed program and arguments
            [
                SECURITY,
                "add-generic-password",
                "-U",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
                secret,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise cr.ConfigureError(
                f"could not store {account} in the Keychain (security exited {result.returncode})"
            )


class SharedTransport(httpx.HTTPTransport):
    """A transport that several short-lived clients share.

    Each client closes its transport when it closes, and the lab script opens a
    client per sign-in and per session, so closing is left to the process exit.
    """

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class Options:
    ip: str
    key: Path
    state_dir: Path
    wait_seconds: float = 1200.0
    poll_seconds: float = 10.0
    token_days: int = 1

    @property
    def url(self) -> str:
        return f"https://{self.ip}"


@dataclass(frozen=True)
class Seams:
    """What the script reaches outside Rancher's API; tests replace each one."""

    keychain: Keychain
    read_log: Callable[[], str]
    insecure: httpx.BaseTransport
    pinned: Callable[[str], httpx.BaseTransport]
    clock: Any


def _items(collection: JSON) -> list[JSON]:
    data = collection.get("data")
    if not isinstance(data, list):
        raise cr.RancherError("Rancher answered a list request without a data list")
    return [item for item in data if isinstance(item, dict)]


def _text(obj: JSON, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise cr.RancherError(f"Rancher's answer has no {key}")
    return value


def read_container_log(options: Options) -> str:
    """Return the Rancher container's log, read over SSH as the ubuntu user."""
    command = [
        SSH,
        "-i",
        str(options.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"UserKnownHostsFile={options.state_dir / 'known_hosts'}",
        "-o",
        "ConnectTimeout=15",
        f"ubuntu@{options.ip}",
        "sudo docker logs rancher 2>&1",
    ]
    try:
        result = subprocess.run(  # noqa: S603 - the address was checked as a public IPv4
            command, capture_output=True, text=True, timeout=120, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise cr.ConfigureError("SSH to the instance timed out") from error
    if result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        last = lines[-1] if lines else "no message"
        last = last.replace(options.ip, "<ip>")
        raise cr.ConfigureError(f"SSH to the instance failed (exit {result.returncode}): {last}")
    return result.stdout


def wait_for_rancher(options: Options, seams: Seams, console: Any) -> str:
    """Return Rancher's CA certificate, once Rancher has finished starting.

    /ping answers as soon as Rancher's listener is up, while its other routes still
    answer 503 for a few minutes. So the wait ends only when /cacerts serves the CA.
    """
    deadline = seams.clock.monotonic() + options.wait_seconds
    said = ""
    with httpx.Client(base_url=options.url, transport=seams.insecure, timeout=10.0) as client:
        while True:
            try:
                ping = client.get("/ping")
                if ping.status_code == 200 and ping.text.strip() == "pong":
                    answer = client.get("/cacerts")
                    text = answer.text.strip()
                    if answer.status_code == 200 and "BEGIN CERTIFICATE" in text:
                        return text + "\n"
                    last = f"/cacerts answered HTTP {answer.status_code}"
                    if answer.status_code == 200:
                        last += " with no certificate"
                else:
                    last = f"/ping answered HTTP {ping.status_code}"
            except httpx.HTTPError as error:
                last = type(error).__name__
            if last != said:
                console.say(f"Rancher is still starting ({last}) ...")
                said = last
            if seams.clock.monotonic() >= deadline:
                raise cr.ConfigureError(
                    f"Rancher did not finish starting (last answer: {last}). See what the "
                    "container is doing: ssh -i ~/.ssh/rancher-spike.pem ubuntu@$SPIKE_IP "
                    "'sudo docker ps -a; sudo docker logs --tail 40 rancher 2>&1 | "
                    'grep -v -i -E "password|setup="\''
                )
            seams.clock.sleep(options.poll_seconds)


def sign_in(
    options: Options,
    seams: Seams,
    transport: httpx.BaseTransport,
    username: str,
    password: str,
) -> str:
    """Sign in as a local user, retrying while Rancher answers 5xx as it starts.

    Any other refusal, such as a wrong password (401), is raised at once.
    """
    deadline = seams.clock.monotonic() + options.wait_seconds
    while True:
        try:
            return str(cr.login(options.url, username, password, transport))
        except cr.ConfigureError as error:
            if not SERVER_ERROR.search(str(error)) or seams.clock.monotonic() >= deadline:
                raise
        seams.clock.sleep(options.poll_seconds)


def pinned_context(ca_pem: str) -> ssl.SSLContext:
    """Trust only Rancher's own CA. The host name is not checked: the certificate
    is made for the container's addresses, not for the instance's public IP."""
    context = ssl.create_default_context(cadata=ca_pem)
    context.check_hostname = False
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def bootstrap_password(options: Options, seams: Seams) -> str:
    """Return the generated bootstrap password from the container's log, waiting for it."""
    deadline = seams.clock.monotonic() + options.wait_seconds
    while True:
        found = BOOTSTRAP_LINE.findall(seams.read_log())
        if found:
            return str(found[-1])
        if seams.clock.monotonic() >= deadline:
            raise cr.ConfigureError(
                "the container's log shows no bootstrap password. If someone already set "
                "the admin password in the UI, store it with: security "
                f"add-generic-password -U -s {KEYCHAIN_SERVICE} -a {ADMIN} -w"
            )
        seams.clock.sleep(options.poll_seconds)


def sign_in_as_admin(
    options: Options, seams: Seams, transport: httpx.BaseTransport, console: Any
) -> str:
    """Sign in as admin and return the session token, replacing the bootstrap password."""
    stored = seams.keychain.get(ADMIN)
    if stored:
        console.secret(stored)
        try:
            session: str = console.secret(sign_in(options, seams, transport, ADMIN, stored))
            console.say("Admin: signed in with the password in your Keychain.")
            return session
        except cr.ConfigureError:
            console.say("Admin: the password in your Keychain does not sign in here.")
    console.say("Admin: reading the bootstrap password from the container's log ...")
    initial = console.secret(bootstrap_password(options, seams))
    session = console.secret(sign_in(options, seams, transport, ADMIN, initial))
    new_password = console.secret(secrets.token_urlsafe(32))
    seams.keychain.put(ADMIN, new_password)
    with cr.RancherAPI(options.url, session, console, transport) as api:
        admins = _items(api.get("/v3/users", {"username": ADMIN}))
        if len(admins) != 1:
            raise cr.RancherError(f"expected one local admin user, found {len(admins)}")
        admin_id = _text(admins[0], "id")
        api.post(f"/v3/users/{admin_id}", {"newPassword": new_password}, {"action": "setpassword"})
    console.say("Admin: replaced the bootstrap password with a new one, kept in your Keychain.")
    return session


def issue_agent_token(
    options: Options,
    seams: Seams,
    transport: httpx.BaseTransport,
    agent_password: str,
    console: Any,
) -> str:
    """Issue sre-agent's API token, store it, prove it signs in, and delete older ones."""
    session = console.secret(sign_in(options, seams, transport, AGENT_USERNAME, agent_password))
    with cr.RancherAPI(options.url, session, console, transport) as agent:
        created = agent.post(
            "/v3/tokens",
            {
                "type": "token",
                "description": TOKEN_DESCRIPTION,
                "ttl": options.token_days * cr.MILLISECONDS_PER_DAY,
            },
        )
        token = console.secret(_text(created, "token"))
        seams.keychain.put(AGENT_TOKEN_ACCOUNT, token)
        name = token.split(":", 1)[0]
        # Rancher sets expiresAt on a token's first use, so this read starts the clock.
        with cr.RancherAPI(options.url, token, console, transport) as stored:
            expires = stored.get(f"/v3/tokens/{name}").get("expiresAt")
        for old in _items(agent.get("/v3/tokens")):
            old_name = old.get("name")
            if old.get("description") == TOKEN_DESCRIPTION and old_name != name:
                agent.delete(f"/v3/tokens/{old_name}")
                console.say("Token: deleted one that an earlier run issued.")
        cr.end_session(agent, session, console)
    return str(expires or f"in {options.token_days} day(s)")


def configure(options: Options, seams: Seams, console: Any) -> None:
    """Run every step in order. Each one is safe to repeat."""
    options.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    console.say(f"Waiting for Rancher at {options.url} ...")
    ca_pem = wait_for_rancher(options, seams, console)
    ca_path = options.state_dir / "rancher-ca.pem"
    ca_path.write_text(ca_pem)
    console.say(f"CA: saved Rancher's CA to {ca_path}; later calls trust only it.")
    transport = seams.pinned(ca_pem)
    session = sign_in_as_admin(options, seams, transport, console)
    agent_password = console.secret(secrets.token_urlsafe(32))
    with cr.RancherAPI(options.url, session, console, transport) as api:
        cr.ensure_setting(api, "server-url", options.url, console)
        role_id = cr.ensure_role_template(api, ROLE_TEMPLATE, console)
        seams.keychain.put(AGENT_USERNAME, agent_password)
        user_id = cr.ensure_agent_user(api, AGENT_USERNAME, agent_password, console)
        cr.ensure_login_access_only(api, user_id, console)
        cr.ensure_cluster_binding(api, LOCAL_CLUSTER, user_id, role_id, console)
        console.say(
            f"Access: {AGENT_USERNAME} has login access only, plus {ROLE_TEMPLATE} "
            f"on the {LOCAL_CLUSTER} cluster."
        )
        expires = issue_agent_token(options, seams, transport, agent_password, console)
        cr.end_session(api, session, console)
    url_file = options.state_dir / "rancher-url"
    url_file.write_text(options.url + "\n")
    url_file.chmod(0o600)
    console.say(f"Rancher's UI: {options.url} (admin password: Keychain, account admin).")
    console.say(
        f"Spike Rancher is ready: sre-agent's token signs in and expires {expires}. "
        "Keychain service rancher-spike holds admin, sre-agent and sre-agent-token."
    )


def parse_args(argv: Sequence[str] | None) -> Options:
    parser = argparse.ArgumentParser(
        description="Spike A, A2 and A3: set up the spike's Rancher for the read-only agent."
    )
    parser.add_argument("ip", help="the public IPv4 address of the rancher-spike instance")
    parser.add_argument(
        "--key", type=Path, default=Path.home() / ".ssh" / "rancher-spike.pem", help="SSH key"
    )
    parser.add_argument("--wait-minutes", type=float, default=20.0)
    parser.add_argument("--token-days", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        address = ipaddress.ip_address(args.ip)
    except ValueError:
        parser.error(
            "the first argument is not an IP address. Is the rancher-spike instance running?"
        )
    if address.version != 4 or not address.is_global:
        parser.error("the first argument must be the instance's public IPv4 address")
    return Options(
        ip=str(address),
        key=args.key.expanduser(),
        state_dir=Path.home() / ".rancher-spike",
        wait_seconds=args.wait_minutes * 60,
        token_days=args.token_days,
    )


def run(options: Options, seams: Seams, console: Any) -> int:
    try:
        configure(options, seams, console)
    except cr.ConfigureError as error:
        message = console.redact(f"{error}. Fix the cause and run the same command again.")
        print(f"configure_spike_rancher: {message}", file=console.err, flush=True)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    console = cr.Console()
    seams = Seams(
        keychain=MacKeychain(),
        read_log=lambda: read_container_log(options),
        insecure=SharedTransport(verify=False),
        pinned=lambda ca: SharedTransport(verify=pinned_context(ca)),
        clock=cr.Clock(),
    )
    return run(options, seams, console)


if __name__ == "__main__":
    raise SystemExit(main())
