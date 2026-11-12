"""Fixtures for the tests of the lab scripts in tools/lab/ (plan Step 11).

AWS is moto, in-process. Rancher is ``FakeRancher``: an in-memory stand-in that
answers the API calls tools/lab/configure_rancher.py makes, with the response
shapes of Rancher 2.15's v1-public login, v3 (Norman) and v1 (Steve) APIs. Every
address and value here is synthetic: example.com names and generated secrets.
"""

import importlib.util
import json
import secrets
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
import httpx
import pytest
from moto import mock_aws

LAB_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "lab"
REGION = "us-east-1"
DOMAIN = "example.com"
RANCHER_HOST = f"rancher.{DOMAIN}"
ADMIN_CREDENTIAL = "sre-lab/rancher-admin-password"
AGENT_CREDENTIAL = "sre-lab/rancher-agent-token"

JSON = dict[str, Any]


def load_script(path: Path) -> ModuleType:
    """Load a script from its path: tools/lab/ is a script folder, not a package."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def configure_rancher() -> ModuleType:
    """tools/lab/configure_rancher.py."""
    return load_script(LAB_TOOLS / "configure_rancher.py")


@pytest.fixture(scope="session")
def put_secret_value() -> ModuleType:
    """tools/lab/rancher_host/put_secret_value.py."""
    return load_script(LAB_TOOLS / "rancher_host" / "put_secret_value.py")


@dataclass
class FakeClock:
    """A clock whose sleep only moves time forward, so waits finish at once."""

    now: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(configure_rancher: ModuleType) -> tuple[FakeClock, Any]:
    """A fake clock, and the script's Clock built on it."""
    fake = FakeClock()
    return fake, configure_rancher.Clock(sleep=fake.sleep, monotonic=fake.monotonic)


@dataclass
class LabAws:
    """The moto-backed account: what infra/aws/permanent and infra/aws/lab create."""

    session: boto3.Session
    admin_password: str
    user_pool_id: str
    client_secret: str
    operator_sub: str

    def secret_value(self, name: str) -> str | None:
        client = self.session.client("secretsmanager")
        try:
            return client.get_secret_value(SecretId=name)["SecretString"]
        except client.exceptions.ResourceNotFoundException:
            return None

    def set_mfa(self, configuration: str) -> None:
        self.session.client("cognito-idp").set_user_pool_mfa_config(
            UserPoolId=self.user_pool_id,
            SoftwareTokenMfaConfiguration={"Enabled": True},
            MfaConfiguration=configuration,
        )


@pytest.fixture
def lab_aws(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[LabAws]:
    """A fake account holding the SSM parameter, both secrets and the Cognito pool."""
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        session = boto3.Session(region_name=REGION)
        session.client("ssm").put_parameter(
            Name="/sre-lab/domain-name", Value=DOMAIN, Type="String"
        )
        admin_password = secrets.token_urlsafe(40)
        sm = session.client("secretsmanager")
        sm.create_secret(Name=ADMIN_CREDENTIAL, SecretString=admin_password)
        sm.create_secret(Name=AGENT_CREDENTIAL)
        cognito = session.client("cognito-idp")
        pool_id = cognito.create_user_pool(PoolName="sre-lab")["UserPool"]["Id"]
        cognito.set_user_pool_mfa_config(
            UserPoolId=pool_id,
            SoftwareTokenMfaConfiguration={"Enabled": True},
            MfaConfiguration="ON",
        )
        client = cognito.create_user_pool_client(
            UserPoolId=pool_id, ClientName="rancher", GenerateSecret=True
        )["UserPoolClient"]
        user = cognito.admin_create_user(
            UserPoolId=pool_id,
            Username="operator",
            UserAttributes=[{"Name": "email", "Value": "operator@example.com"}],
        )["User"]
        sub = next(a["Value"] for a in user["Attributes"] if a["Name"] == "sub")
        yield LabAws(session, admin_password, pool_id, client["ClientSecret"], sub)


def _error(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"type": "error", "code": code, "message": code.lower()})


def _collection(items: list[JSON]) -> httpx.Response:
    return httpx.Response(200, json={"type": "collection", "data": items})


@dataclass
class FakeRancher:
    """An in-memory Rancher API for configure_rancher.py.

    Switches: ``ready`` (answers /ping), ``reject_logins``,
    ``refuse_global_role_bindings`` (the /v1 API refuses new bindings), and
    ``polls_until_active``: how many cluster reads after the registration command
    was handed out before the cluster turns active, or None for never.
    """

    admin_password: str
    ready: bool = True
    reject_logins: bool = False
    refuse_global_role_bindings: bool = False
    polls_until_active: int | None = 1
    passwords: dict[str, str] = field(default_factory=dict)
    users: dict[str, JSON] = field(default_factory=dict)
    tokens: dict[str, JSON] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=lambda: {"server-url": ""})
    authconfig: JSON = field(default_factory=dict)
    globalrolebindings: dict[str, JSON] = field(default_factory=dict)
    roletemplates: dict[str, JSON] = field(default_factory=dict)
    clusters: dict[str, JSON] = field(default_factory=dict)
    crtbs: dict[str, JSON] = field(default_factory=dict)
    registration_tokens: dict[str, JSON] = field(default_factory=dict)
    gitrepos: dict[str, JSON] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    issued_bearers: list[str] = field(default_factory=list)
    commands_handed_out: int = 0
    _next: int = 0

    def __post_init__(self) -> None:
        self.passwords["admin"] = self.admin_password
        self.users["user-admin"] = {
            "id": "user-admin",
            "type": "user",
            "username": "admin",
            "mustChangePassword": True,
            "enabled": True,
        }
        self.authconfig = {
            "id": "cognito",
            "type": "cognitoConfig",
            "name": "cognito",
            "enabled": False,
            "links": {"self": f"https://{RANCHER_HOST}/v3/cognitoConfigs/cognito"},
        }

    # Helpers for tests ------------------------------------------------------

    def new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}-{self._next:05d}"

    def writes(self) -> list[tuple[str, str]]:
        return [(method, path) for method, path in self.calls if method != "GET"]

    def user_id(self, username: str) -> str:
        return next(uid for uid, user in self.users.items() if user.get("username") == username)

    def api_tokens_of(self, username: str) -> list[JSON]:
        uid = self.user_id(username)
        return [t for t in self.tokens.values() if t["userId"] == uid and t["kind"] != "session"]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    # Request handling -------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if path == "/ping":
            return httpx.Response(200, text="pong") if self.ready else _error(503, "Unavailable")
        if path == "/v1-public/login" and request.method == "POST":
            return self._login(json.loads(request.content))
        caller = self._caller(request)
        if caller is None:
            return _error(401, "Unauthorized")
        body = json.loads(request.content) if request.content else {}
        return self._route(request.method, path, dict(request.url.params), body, caller)

    def _caller(self, request: httpx.Request) -> str | None:
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        name, _, key = bearer.partition(":")
        token = self.tokens.get(name)
        return token["userId"] if token and token["key"] == key else None

    def _issue(self, user_id: str, kind: str, description: str, ttl: int = 0) -> JSON:
        name = self.new_id("token")
        key = secrets.token_urlsafe(32)
        self.tokens[name] = {
            "id": name,
            "name": name,
            "type": "token",
            "userId": user_id,
            "kind": kind,
            "description": description,
            "ttl": ttl,
            "key": key,
        }
        bearer = f"{name}:{key}"
        self.issued_bearers.append(bearer)
        return {"id": name, "name": name, "type": "token", "token": bearer, "expiresAt": "later"}

    def _login(self, body: JSON) -> httpx.Response:
        username = body.get("username", "")
        if self.reject_logins or self.passwords.get(username) != body.get("password"):
            return _error(401, "Unauthorized")
        issued = self._issue(self.user_id(username), "session", body.get("description", ""))
        return httpx.Response(201, json=issued)

    def _route(
        self, method: str, path: str, params: dict[str, str], body: JSON, caller: str
    ) -> httpx.Response:
        parts = path.strip("/").split("/")
        if parts[:2] == ["v3", "tokens"]:
            return self._tokens(method, parts, body, caller)
        if caller != "user-admin":
            return _error(403, "Forbidden")
        if parts[:2] == ["v3", "settings"]:
            return self._settings(method, parts[2], body)
        if parts[:2] in (["v3", "authConfigs"], ["v3", "cognitoConfigs"]):
            if method == "PUT":
                self.authconfig.update(body)
            return httpx.Response(200, json=self.authconfig)
        if parts[:2] == ["v3", "users"]:
            return self._users(method, parts, params, body)
        if parts[:2] == ["v3", "clusters"]:
            return self._clusters(method, parts, params, body)
        if parts[:2] == ["v3", "clusterregistrationtokens"]:
            return self._registration_tokens(method, params, body)
        if parts[:2] == ["v1", "fleet.cattle.io.gitrepos"]:
            return self._gitrepos(method, parts, body)
        if parts[:2] == ["v1", "management.cattle.io.globalrolebindings"]:
            return self._v1_globalrolebindings(method, body)
        if parts[:2] == ["v3", "globalrolebindings"]:
            return self._v3_globalrolebindings(method, parts, params, body)
        collections = {
            "roletemplates": (self.roletemplates, "rt"),
            "clusterroletemplatebindings": (self.crtbs, "crtb"),
        }
        store, prefix = collections[parts[1]]
        return self._generic(store, prefix, method, parts, params, body)

    def _generic(
        self,
        store: dict[str, JSON],
        prefix: str,
        method: str,
        parts: list[str],
        params: dict[str, str],
        body: JSON,
    ) -> httpx.Response:
        if method == "GET":
            return _collection([o for o in store.values() if _matches(o, params)])
        if method == "POST":
            new = {**body, "id": self.new_id(prefix)}
            store[new["id"]] = new
            return httpx.Response(201, json=new)
        if method == "PUT":
            store[parts[2]].update(body)
            return httpx.Response(200, json=store[parts[2]])
        store.pop(parts[2])
        return httpx.Response(200, json={})

    def _v3_globalrolebindings(
        self, method: str, parts: list[str], params: dict[str, str], body: JSON
    ) -> httpx.Response:
        """Rancher 2.15's v3 validator: a new binding names exactly one user or one group.

        A binding that names only a user principal is refused, as the real Rancher
        refused it (pkg/api/norman/customization/globalrolebinding/validator.go).
        """
        if method == "POST" and (body.get("userId") is None) == (
            body.get("groupPrincipalId") is None
        ):
            return httpx.Response(
                422,
                json={
                    "type": "error",
                    "code": "InvalidBodyContent",
                    "message": "must contain field [groupPrincipalId] OR field [userId]",
                },
            )
        return self._generic(self.globalrolebindings, "grb", method, parts, params, body)

    def _v1_globalrolebindings(self, method: str, body: JSON) -> httpx.Response:
        """The /v1 (Kubernetes) view of the same bindings, with the webhook and controller rules.

        The webhook needs a user (userName or userPrincipalName) or a group, not both.
        For a binding that names only a user principal, the controller creates the
        Rancher user for that principal and binds the role to it.
        """
        if method == "GET":
            return _collection([_as_v1_binding(g) for g in self.globalrolebindings.values()])
        principal = body.get("userPrincipalName")
        group = body.get("groupPrincipalName")
        if self.refuse_global_role_bindings or bool(body.get("userName") or principal) == bool(
            group
        ):
            return _error(422, "Invalid")
        binding_id = self.new_id("grb")
        binding: JSON = {"id": binding_id, "globalRoleId": body["globalRoleName"]}
        if group:
            binding["groupPrincipalId"] = group
        else:
            binding["userId"] = body.get("userName") or self._ensure_user(principal)
            binding["userPrincipalId"] = principal
        self.globalrolebindings[binding_id] = binding
        return httpx.Response(201, json=_as_v1_binding(binding))

    def _ensure_user(self, principal: str) -> str:
        """Return the user that holds ``principal``, creating it as Rancher's EnsureUser does."""
        for user_id, user in self.users.items():
            if principal in user.get("principalIds", []):
                return user_id
        user_id = self.new_id("u")
        self.users[user_id] = {
            "id": user_id,
            "type": "user",
            "principalIds": [principal],
            "enabled": True,
        }
        return user_id

    def _settings(self, method: str, name: str, body: JSON) -> httpx.Response:
        if method == "PUT":
            self.settings[name] = body["value"]
        return httpx.Response(200, json={"id": name, "value": self.settings.get(name, "")})

    def _users(
        self, method: str, parts: list[str], params: dict[str, str], body: JSON
    ) -> httpx.Response:
        if method == "GET":
            return _collection([u for u in self.users.values() if _matches(u, params)])
        if method == "POST" and len(parts) == 2:
            uid = self.new_id("u")
            self.passwords[body["username"]] = body.pop("password")
            self.users[uid] = {**body, "id": uid}
            return httpx.Response(201, json=self.users[uid])
        user = self.users[parts[2]]
        if params.get("action") == "setpassword":
            self.passwords[user["username"]] = body["newPassword"]
            user["mustChangePassword"] = False
        else:
            user.update(body)
        return httpx.Response(200, json=user)

    def _clusters(
        self, method: str, parts: list[str], params: dict[str, str], body: JSON
    ) -> httpx.Response:
        if method == "POST":
            cid = self.new_id("c")
            self.clusters[cid] = {**body, "id": cid, "state": "pending"}
            return httpx.Response(201, json=self.clusters[cid])
        if len(parts) == 2:
            return _collection([c for c in self.clusters.values() if _matches(c, params)])
        cluster = self.clusters[parts[2]]
        if method == "PUT":
            cluster.update(body)
        elif cluster["state"] != "active" and self.commands_handed_out:
            self._maybe_activate(cluster)
        return httpx.Response(200, json=cluster)

    def _maybe_activate(self, cluster: JSON) -> None:
        if self.polls_until_active is None:
            return
        if self.polls_until_active <= 0:
            cluster["state"] = "active"
        self.polls_until_active -= 1

    def _registration_tokens(
        self, method: str, params: dict[str, str], body: JSON
    ) -> httpx.Response:
        if method == "POST":
            tid = self.new_id("crt")
            command = (
                f"kubectl apply -f https://{RANCHER_HOST}/v3/import/"
                f"{secrets.token_hex(8)}_{body['clusterId']}.yaml"
            )
            self.registration_tokens[tid] = {**body, "id": tid, "command": command}
            return httpx.Response(201, json=self.registration_tokens[tid])
        found = [t for t in self.registration_tokens.values() if _matches(t, params)]
        if found:
            self.commands_handed_out += 1
        return _collection(found)

    def _gitrepos(self, method: str, parts: list[str], body: JSON) -> httpx.Response:
        if method == "POST":
            key = f"{body['metadata']['namespace']}/{body['metadata']['name']}"
            self.gitrepos[key] = {
                **body,
                "id": key,
                "metadata": {**body["metadata"], "resourceVersion": "1"},
            }
            return httpx.Response(201, json=self.gitrepos[key])
        key = "/".join(parts[2:4])
        if key not in self.gitrepos:
            return _error(404, "NotFound")
        if method == "PUT":
            self.gitrepos[key] = body
        return httpx.Response(200, json=self.gitrepos[key])

    def _tokens(self, method: str, parts: list[str], body: JSON, caller: str) -> httpx.Response:
        if method == "POST":
            ttl = int(body.get("ttl", 0))
            return httpx.Response(
                201, json=self._issue(caller, "", body.get("description", ""), ttl)
            )
        if method == "GET":
            mine = [t for t in self.tokens.values() if t["userId"] == caller]
            return _collection([{k: v for k, v in t.items() if k != "key"} for t in mine])
        token = self.tokens.get(parts[2])
        if token is None or (token["userId"] != caller and caller != "user-admin"):
            return _error(404, "NotFound")
        del self.tokens[parts[2]]
        return httpx.Response(200, json={})


def _matches(item: JSON, params: dict[str, str]) -> bool:
    return all(str(item.get(key)) == value for key, value in params.items())


def _as_v1_binding(binding: JSON) -> JSON:
    """Show a stored binding as Rancher's /v1 API does, with Kubernetes field names."""
    fields = {
        "globalRoleName": binding.get("globalRoleId"),
        "userName": binding.get("userId"),
        "userPrincipalName": binding.get("userPrincipalId"),
        "groupPrincipalName": binding.get("groupPrincipalId"),
    }
    return {
        "id": binding["id"],
        "type": "management.cattle.io.globalrolebinding",
        "metadata": {"name": binding["id"]},
        **{key: value for key, value in fields.items() if value is not None},
    }


@pytest.fixture
def rancher(lab_aws: LabAws) -> FakeRancher:
    """A fresh Rancher, as the Rancher host leaves it after its first boot."""
    return FakeRancher(admin_password=lab_aws.admin_password)
