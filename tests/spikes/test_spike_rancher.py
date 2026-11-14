"""Tests for tools/spikes/spike-a/configure_spike_rancher.py."""

import datetime
import importlib.util
import io
import ipaddress
import secrets
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

REPO = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


spike = _load("configure_spike_rancher", REPO / "tools/spikes/spike-a/configure_spike_rancher.py")
lab = _load("lab_conftest", REPO / "tests/u1/tools_lab/conftest.py")

FAKE_CA = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----"
# A documentation address (RFC 5737): the probe never connects to it.
IP = "203.0.113.10"


class FakeKeychain:
    def __init__(self, items=None):
        self.items = dict(items or {})

    def get(self, account):
        return self.items.get(account)

    def put(self, account, secret):
        self.items[account] = secret


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


@pytest.fixture
def rancher():
    return lab.FakeRancher(admin_password="bootstrap-" + secrets.token_urlsafe(16))


def make(rancher, keychain, tmp_path, log_text=None, wait_seconds=60.0, early=None, login_503=0):
    log_calls = []
    early = list(early or [])
    refusals = [login_503]

    def read_log():
        log_calls.append(1)
        if log_text is not None:
            return log_text
        return (
            "2026/11/13 20:45:12 [INFO] A bootstrap password has been generated"
            " for your admin user.\n"
            f"2026/11/13 20:45:12 [INFO] Bootstrap Password: {rancher.admin_password}\n"
            f"2026/11/13 20:45:12 [INFO] Use https://192.0.2.2/dashboard/?setup={rancher.admin_password}\n"
        )

    def handler(request):
        if request.url.path == "/cacerts":
            if early:
                return early.pop(0)
            return httpx.Response(200, text=FAKE_CA)
        if request.url.path == "/v1-public/login" and refusals[0] > 0:
            refusals[0] -= 1
            return httpx.Response(503, text="waiting")
        return rancher.handle(request)

    transport = httpx.MockTransport(handler)
    pinned_with = []

    def pinned(ca):
        pinned_with.append(ca)
        return transport

    clock = FakeClock()
    seams = spike.Seams(
        keychain=keychain,
        read_log=read_log,
        insecure=transport,
        pinned=pinned,
        clock=spike.cr.Clock(sleep=clock.sleep, monotonic=clock.monotonic),
    )
    options = spike.Options(
        ip=IP,
        key=tmp_path / "key.pem",
        state_dir=tmp_path / "state",
        wait_seconds=wait_seconds,
        poll_seconds=10.0,
    )
    out, err = io.StringIO(), io.StringIO()
    console = spike.cr.Console(out=out, err=err)
    return options, seams, console, out, err, log_calls, pinned_with


def agent_bindings(rancher):
    agent_id = rancher.user_id("sre-agent")
    return [g for g in rancher.globalrolebindings.values() if g.get("userId") == agent_id]


def test_first_run_sets_up_everything_and_prints_no_secret(rancher, tmp_path):
    keychain = FakeKeychain()
    options, seams, console, out, err, log_calls, pinned_with = make(rancher, keychain, tmp_path)
    bootstrap = rancher.admin_password

    assert spike.run(options, seams, console) == 0, err.getvalue()

    assert keychain.items["admin"] != bootstrap
    assert rancher.passwords["admin"] == keychain.items["admin"]
    agent_id = rancher.user_id("sre-agent")
    assert rancher.passwords["sre-agent"] == keychain.items["sre-agent"]
    assert [g["globalRoleId"] for g in agent_bindings(rancher)] == ["user-base"]
    (template,) = rancher.roletemplates.values()
    assert template["name"] == "agent-readonly"
    assert template["context"] == "cluster"
    for rule in template["rules"]:
        assert "secrets" not in rule["resources"]
        assert set(rule["verbs"]) <= {"get", "list", "watch"}
    resources = {r for rule in template["rules"] for r in rule["resources"]}
    assert resources == {
        "pods",
        "pods/log",
        "events",
        "namespaces",
        "deployments",
        "replicasets",
        "services",
        "nodes",
    }
    (crtb,) = rancher.crtbs.values()
    assert (crtb["clusterId"], crtb["userId"], crtb["roleTemplateId"]) == (
        "local",
        agent_id,
        template["id"],
    )
    (token,) = rancher.api_tokens_of("sre-agent")
    assert token["ttl"] == 86_400_000
    assert keychain.items["sre-agent-token"] == f"{token['name']}:{token['key']}"
    assert rancher.settings["server-url"] == f"https://{IP}"
    assert not [t for t in rancher.tokens.values() if t["kind"] == "session"]
    assert (tmp_path / "state" / "rancher-ca.pem").read_text() == FAKE_CA + "\n"
    assert (tmp_path / "state" / "rancher-url").read_text() == f"https://{IP}\n"
    assert pinned_with == [FAKE_CA + "\n"]
    assert len(log_calls) == 1
    printed = out.getvalue() + err.getvalue()
    for value in [bootstrap, *keychain.items.values(), *rancher.issued_bearers]:
        assert value not in printed
    last_line = out.getvalue().strip().splitlines()[-1]
    assert last_line.startswith("Spike Rancher is ready")
    assert IP not in last_line
    print(out.getvalue())


def test_second_run_uses_the_stored_admin_password_and_rotates_the_token(rancher, tmp_path):
    keychain = FakeKeychain()
    first = make(rancher, keychain, tmp_path)
    assert spike.run(*first[:3]) == 0
    admin_password = keychain.items["admin"]
    first_token = keychain.items["sre-agent-token"]

    options, seams, console, out, err, log_calls, _ = make(rancher, keychain, tmp_path)
    assert spike.run(options, seams, console) == 0, err.getvalue()

    assert log_calls == []
    assert keychain.items["admin"] == admin_password == rancher.passwords["admin"]
    (token,) = rancher.api_tokens_of("sre-agent")
    assert keychain.items["sre-agent-token"] == f"{token['name']}:{token['key']}"
    assert keychain.items["sre-agent-token"] != first_token
    assert len(rancher.roletemplates) == 1
    assert len(rancher.crtbs) == 1
    assert len(agent_bindings(rancher)) == 1
    assert "Token: deleted one that an earlier run issued." in out.getvalue()
    printed = out.getvalue() + err.getvalue()
    for value in [*keychain.items.values(), first_token]:
        assert value not in printed


def test_a_stale_keychain_password_falls_back_to_the_bootstrap_password(rancher, tmp_path):
    keychain = FakeKeychain({"admin": "from-an-older-spike"})
    options, seams, console, out, err, log_calls, _ = make(rancher, keychain, tmp_path)

    assert spike.run(options, seams, console) == 0, err.getvalue()

    assert log_calls
    assert keychain.items["admin"] != "from-an-older-spike"
    assert rancher.passwords["admin"] == keychain.items["admin"]
    assert "does not sign in here" in out.getvalue()
    assert "from-an-older-spike" not in out.getvalue() + err.getvalue()


def test_no_bootstrap_password_in_the_log_stops_with_advice(rancher, tmp_path):
    keychain = FakeKeychain()
    options, seams, console, _out, err, log_calls, _ = make(
        rancher, keychain, tmp_path, log_text="[INFO] starting\n"
    )

    assert spike.run(options, seams, console) == 1

    assert "no bootstrap password" in err.getvalue()
    assert err.getvalue().startswith("configure_spike_rancher: ")
    assert len(log_calls) > 1
    assert "admin" not in keychain.items
    assert rancher.passwords["admin"] == rancher.admin_password


def test_rancher_that_never_answers_stops_after_the_wait(rancher, tmp_path):
    rancher.ready = False
    keychain = FakeKeychain()
    options, seams, console, _out, err, log_calls, _ = make(rancher, keychain, tmp_path)

    assert spike.run(options, seams, console) == 1

    assert "did not finish starting (last answer: /ping answered HTTP 503)" in err.getvalue()
    assert IP not in err.getvalue()
    assert not rancher.writes()
    assert log_calls == []


def test_the_address_must_be_a_public_ipv4():
    for bad in ("None", "10.0.0.5", "::1", ""):
        with pytest.raises(SystemExit) as raised:
            spike.parse_args([bad])
        assert raised.value.code == 2
    # parse_args accepts only a globally routable address, and the documentation ranges
    # are not global, so this one test uses an arbitrary public address.
    options = spike.parse_args(["54.10.20.30"])
    assert options.url == "https://54.10.20.30"
    assert options.wait_seconds == 1200.0
    assert options.token_days == 1


# A real TLS check of pinned_context and SharedTransport --------------------------


def _ca_and_leaf(san_ip):
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dynamiclistener-ca")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dynamic")]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address(san_ip))]
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    return ca, leaf, leaf_key


class _Ping(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"pong"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def tls_server(tmp_path):
    ca, leaf, leaf_key = _ca_and_leaf("192.0.2.2")
    cert_file = tmp_path / "leaf.pem"
    key_file = tmp_path / "leaf.key"
    cert_file.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server = HTTPServer(("127.0.0.1", 0), _Ping)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield (
        f"https://127.0.0.1:{server.server_address[1]}",
        ca.public_bytes(serialization.Encoding.PEM).decode(),
    )
    server.shutdown()


def test_the_pinned_ca_is_trusted_without_a_matching_ip(tls_server):
    url, ca_pem = tls_server
    transport = spike.SharedTransport(verify=spike.pinned_context(ca_pem))
    for _ in range(2):
        with httpx.Client(base_url=url, transport=transport, timeout=5.0) as client:
            assert client.get("/ping").text == "pong"


def test_another_ca_is_refused(tls_server):
    url, _ = tls_server
    other_ca, _, _ = _ca_and_leaf("192.0.2.2")
    other_pem = other_ca.public_bytes(serialization.Encoding.PEM).decode()
    transport = spike.SharedTransport(verify=spike.pinned_context(other_pem))
    with (
        httpx.Client(base_url=url, transport=transport, timeout=5.0) as client,
        pytest.raises(httpx.ConnectError),
    ):
        client.get("/ping")


def test_the_insecure_transport_reaches_it_for_ping_and_cacerts(tls_server):
    url, _ = tls_server
    transport = spike.SharedTransport(verify=False)
    with httpx.Client(base_url=url, transport=transport, timeout=5.0) as client:
        assert client.get("/ping").text == "pong"


def test_it_waits_while_cacerts_answers_503_or_nothing(rancher, tmp_path):
    keychain = FakeKeychain()
    early = [httpx.Response(503, text="no")] * 3 + [httpx.Response(200, text="")] * 2
    options, seams, console, out, err, _log_calls, pinned_with = make(
        rancher, keychain, tmp_path, early=early
    )

    assert spike.run(options, seams, console) == 0, err.getvalue()

    printed = out.getvalue()
    assert "Rancher is still starting (/cacerts answered HTTP 503) ..." in printed
    assert (
        "Rancher is still starting (/cacerts answered HTTP 200 with no certificate) ..." in printed
    )
    assert printed.count("still starting") == 2
    assert pinned_with == [FAKE_CA + "\n"]
    assert "sre-agent-token" in keychain.items


def test_it_retries_sign_ins_that_rancher_answers_with_503(rancher, tmp_path):
    keychain = FakeKeychain()
    options, seams, console, _out, err, _log_calls, _ = make(
        rancher, keychain, tmp_path, login_503=2
    )

    assert spike.run(options, seams, console) == 0, err.getvalue()
    assert rancher.passwords["admin"] == keychain.items["admin"]


def test_a_rancher_stuck_starting_stops_with_a_diagnostic_command(rancher, tmp_path):
    keychain = FakeKeychain()
    early = [httpx.Response(503, text="no")] * 1000
    options, seams, console, _out, err, log_calls, _ = make(
        rancher, keychain, tmp_path, early=early
    )

    assert spike.run(options, seams, console) == 1

    message = err.getvalue()
    assert "did not finish starting (last answer: /cacerts answered HTTP 503)" in message
    assert "ubuntu@$SPIKE_IP" in message
    assert IP not in message
    assert not rancher.writes()
    assert log_calls == []
