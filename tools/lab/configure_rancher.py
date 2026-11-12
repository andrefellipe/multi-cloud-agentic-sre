#!/usr/bin/env python3
"""Configure the lab's Rancher after you apply ``infra/aws/lab`` (plan Step 10).

You run it from your admin terminal after each lab rebuild. It is idempotent: a
second run finds everything in place and changes nothing, except that it issues
the agent a fresh token, so the token is replaced on every rebuild, well within
its 30-day expiry. In order, it:

1. waits for Rancher at ``https://rancher.<domain>`` (the domain is read from the
   SSM parameter ``/sre-lab/domain-name``), then signs in as the local admin with
   the password the Rancher host wrote to Secrets Manager;
2. keeps that password valid for break-glass use and sets Rancher's server URL;
3. turns on Amazon Cognito sign-in, only if the user pool requires MFA, for your
   ``operator`` user alone, and makes that identity a Rancher admin (REQ-021.1);
4. creates the ``agent-readonly`` cluster role: get, list and watch on pods, pod
   logs, events, namespaces, deployments, replica sets, services and nodes,
   nothing on Secrets and no write verb (REQ-050.1);
5. creates the ``sre-agent`` local user, with login access and nothing else;
6. registers the EKS cluster as an imported cluster labelled ``cloud=aws``, binds
   ``sre-agent`` to it with ``agent-readonly``, prints the one ``kubectl apply``
   command you run against EKS, and waits until the cluster is active;
7. points Fleet at ``platform/`` on ``main`` of the public repository, over HTTPS
   with no credentials, for clusters labelled ``cloud=aws`` (REQ-022);
8. issues the ``sre-agent`` API token with a 30-day expiry, writes it to the
   Secrets Manager secret ``sre-lab/rancher-agent-token``, and deletes the tokens
   earlier runs issued (REQ-050.1, REQ-103.1).

It never prints a password, the Cognito client secret or a Rancher token, and it
makes no write to the EKS cluster: you apply the registration manifest yourself.
Rancher's v3 token API is deprecated since Rancher 2.14 but still served by the
pinned 2.15; move step 8 to ``tokens.ext.cattle.io`` before Rancher removes it.

Usage:
    uv run python tools/lab/configure_rancher.py [--help]

Exit status: 0 when Rancher is configured, 1 when a step fails (fix the cause and
run it again), 2 on a usage error.
"""

from __future__ import annotations

import argparse
import secrets
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, TextIO

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp import CognitoIdentityProviderClient
    from mypy_boto3_secretsmanager import SecretsManagerClient
    from mypy_boto3_ssm import SSMClient

JSON = dict[str, Any]

READ_VERBS = ("get", "list", "watch")
# The agent-readonly cluster role (REQ-050.1, security-design.md SD-4). Nothing on
# Secrets, no write verb, no wildcard. Events are listed in both API groups.
AGENT_READ_RULES: tuple[JSON, ...] = (
    {
        "apiGroups": [""],
        "resources": ["events", "namespaces", "nodes", "pods", "pods/log", "services"],
        "verbs": list(READ_VERBS),
    },
    {"apiGroups": ["apps"], "resources": ["deployments", "replicasets"], "verbs": list(READ_VERBS)},
    {"apiGroups": ["events.k8s.io"], "resources": ["events"], "verbs": list(READ_VERBS)},
)
LOGIN_ONLY_GLOBAL_ROLE = "user-base"
FLEET_WORKSPACE = "fleet-default"
GLOBAL_ROLE_BINDINGS = "/v1/management.cattle.io.globalrolebindings"
AGENT_CREDENTIAL_DESCRIPTION = "sre-agent read token, issued by tools/lab/configure_rancher.py"
MILLISECONDS_PER_DAY = 86_400_000


class ConfigureError(Exception):
    """A step failed. The message is safe to print: it never holds a secret."""


class RancherError(ConfigureError):
    """A Rancher API call failed."""


@dataclass(frozen=True)
class Settings:
    """Names and limits. The defaults match infra/aws/permanent and infra/aws/lab."""

    region: str = "us-east-1"
    domain_parameter: str = "/sre-lab/domain-name"
    # Names of Secrets Manager secrets (the values never appear in this file).
    admin_credential_name: str = "sre-lab/rancher-admin-password"
    agent_credential_name: str = "sre-lab/rancher-agent-token"
    user_pool_name: str = "sre-lab"
    app_client_name: str = "rancher"
    operator_username: str = "operator"
    cluster_name: str = "sre-lab-eks"
    agent_username: str = "sre-agent"
    role_template_name: str = "agent-readonly"
    gitrepo_name: str = "sre-lab-platform"
    repo_url: str = "https://github.com/andrefellipe/multi-cloud-agentic-sre"
    branch: str = "main"
    fleet_path: str = "platform"
    token_ttl_days: int = 30
    wait_seconds: float = 1800.0
    poll_seconds: float = 10.0


@dataclass(frozen=True)
class Clock:
    """Time functions, replaced in tests so that waits take no real time."""

    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


@dataclass
class Console:
    """Prints progress and errors, with every registered secret value redacted."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)
    _secrets: set[str] = field(default_factory=set, init=False, repr=False)

    def secret(self, value: str) -> str:
        """Register ``value`` so that it is never printed, and return it."""
        if value:
            self._secrets.add(value)
        return value

    def redact(self, text: str) -> str:
        """Return ``text`` with every registered secret value replaced."""
        for value in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(value, "[redacted]")
        return text

    def say(self, text: str) -> None:
        print(self.redact(text), file=self.out, flush=True)

    def error(self, text: str) -> None:
        print(f"configure_rancher: {self.redact(text)}", file=self.err, flush=True)


@dataclass(frozen=True)
class AwsClients:
    """The AWS clients the script uses, all from your admin profile."""

    ssm: SSMClient
    secrets: SecretsManagerClient
    cognito: CognitoIdentityProviderClient

    @classmethod
    def from_session(cls, session: boto3.Session) -> AwsClients:
        return cls(
            ssm=session.client("ssm"),
            secrets=session.client("secretsmanager"),
            cognito=session.client("cognito-idp"),
        )


@dataclass(frozen=True)
class CognitoSignIn:
    """What Rancher needs to sign the operator in through Cognito."""

    issuer: str
    client_id: str
    client_secret: str
    principal_id: str


def _items(collection: JSON) -> list[JSON]:
    data = collection.get("data")
    if not isinstance(data, list):
        raise RancherError("Rancher answered a list request without a data list")
    return [item for item in data if isinstance(item, dict)]


def _text(obj: Mapping[str, Any], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value:
        raise RancherError(f"Rancher's answer has no {key}")
    return value


class RancherAPI:
    """A signed-in session with Rancher's API. Errors never quote request bodies."""

    def __init__(
        self,
        rancher_url: str,
        token: str,
        console: Console,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._console = console
        self._client = httpx.Client(
            base_url=rancher_url,
            transport=transport,
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def __enter__(self) -> RancherAPI:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._client.close()

    def _send(
        self,
        method: str,
        path: str,
        body: JSON | None = None,
        params: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, json=body, params=params)
        except httpx.HTTPError as error:
            raise RancherError(f"{method} {path} failed: {type(error).__name__}") from error

    def _decode(self, method: str, path: str, response: httpx.Response) -> JSON:
        if response.status_code >= 300:
            detail = ""
            try:
                payload = response.json()
                if isinstance(payload, dict):
                    detail = f" {payload.get('code', '')}: {str(payload.get('message', ''))[:200]}"
            except ValueError:
                pass
            raise RancherError(
                self._console.redact(f"{method} {path} failed: HTTP {response.status_code}{detail}")
            )
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise RancherError(f"{method} {path} returned something other than an object")
        return payload

    def get(self, path: str, params: Mapping[str, str] | None = None) -> JSON:
        return self._decode("GET", path, self._send("GET", path, params=params))

    def get_optional(self, path: str) -> JSON | None:
        """Return the object at ``path``, or None when Rancher answers 404."""
        response = self._send("GET", path)
        if response.status_code == 404:
            return None
        return self._decode("GET", path, response)

    def post(self, path: str, body: JSON, params: Mapping[str, str] | None = None) -> JSON:
        return self._decode("POST", path, self._send("POST", path, body, params))

    def put(self, path: str, body: JSON) -> JSON:
        return self._decode("PUT", path, self._send("PUT", path, body))

    def delete(self, path: str) -> None:
        self._decode("DELETE", path, self._send("DELETE", path))


def read_parameter(ssm: SSMClient, name: str) -> str:
    """Return the value of a plain String SSM parameter."""
    try:
        value = ssm.get_parameter(Name=name)["Parameter"].get("Value", "")
    except ssm.exceptions.ParameterNotFound as error:
        raise ConfigureError(f"the SSM parameter {name} does not exist") from error
    if not value.strip():
        raise ConfigureError(f"the SSM parameter {name} is empty")
    return value.strip()


def wait_for_secret(
    client: SecretsManagerClient, secret_id: str, settings: Settings, clock: Clock
) -> str:
    """Return the current value of ``secret_id``, waiting while it has none yet."""
    deadline = clock.monotonic() + settings.wait_seconds
    while True:
        try:
            value = client.get_secret_value(SecretId=secret_id).get("SecretString", "")
            if value:
                return value
        except client.exceptions.ResourceNotFoundException:
            pass
        if clock.monotonic() >= deadline:
            raise ConfigureError(
                f"the secret {secret_id} still has no value. The Rancher host writes it at first "
                "boot; read its log with Session Manager: journalctl -t rancher-bootstrap"
            )
        clock.sleep(settings.poll_seconds)


def write_secret(client: SecretsManagerClient, secret_id: str, value: str) -> None:
    """Store ``value`` as the current version of ``secret_id``, which Terraform created."""
    try:
        client.put_secret_value(SecretId=secret_id, SecretString=value)
    except client.exceptions.ResourceNotFoundException as error:
        raise ConfigureError(
            f"the secret {secret_id} does not exist; apply infra/aws/lab first"
        ) from error


def _find_user_pool(cognito: CognitoIdentityProviderClient, name: str) -> str:
    pages = cognito.get_paginator("list_user_pools").paginate(PaginationConfig={"PageSize": 60})
    pool_ids = [pool["Id"] for page in pages for pool in page["UserPools"] if pool["Name"] == name]
    if len(pool_ids) != 1:
        raise ConfigureError(f"expected one Cognito user pool named {name}, found {len(pool_ids)}")
    return pool_ids[0]


def _find_app_client(cognito: CognitoIdentityProviderClient, pool_id: str, name: str) -> str:
    pages = cognito.get_paginator("list_user_pool_clients").paginate(
        UserPoolId=pool_id, PaginationConfig={"PageSize": 60}
    )
    client_ids = [
        client["ClientId"]
        for page in pages
        for client in page["UserPoolClients"]
        if client.get("ClientName") == name
    ]
    if len(client_ids) != 1:
        raise ConfigureError(
            f"expected one Cognito app client named {name}, found {len(client_ids)}"
        )
    return client_ids[0]


def read_cognito(cognito: CognitoIdentityProviderClient, settings: Settings) -> CognitoSignIn:
    """Look up the pool, the Rancher app client and the operator, and check MFA is required."""
    pool_id = _find_user_pool(cognito, settings.user_pool_name)
    mfa = cognito.get_user_pool_mfa_config(UserPoolId=pool_id).get("MfaConfiguration")
    if mfa != "ON":
        raise ConfigureError(
            f"the user pool {settings.user_pool_name} does not require MFA (MfaConfiguration "
            f"{mfa}); Rancher sign-in stays off until it does (REQ-021.1)"
        )
    client_id = _find_app_client(cognito, pool_id, settings.app_client_name)
    described = cognito.describe_user_pool_client(UserPoolId=pool_id, ClientId=client_id)
    client_secret = described["UserPoolClient"].get("ClientSecret", "")
    if not client_secret:
        raise ConfigureError(
            f"the app client {settings.app_client_name} has no secret; Rancher's Cognito "
            "sign-in requires a confidential client"
        )
    user = cognito.admin_get_user(UserPoolId=pool_id, Username=settings.operator_username)
    subs = [
        a["Value"] for a in user.get("UserAttributes", []) if a["Name"] == "sub" and a.get("Value")
    ]
    if not subs:
        raise ConfigureError(f"the Cognito user {settings.operator_username} has no sub attribute")
    return CognitoSignIn(
        issuer=f"https://cognito-idp.{settings.region}.amazonaws.com/{pool_id}",
        client_id=client_id,
        client_secret=client_secret,
        principal_id=f"cognito_user://{subs[0]}",
    )


def wait_for_rancher(
    rancher_url: str, settings: Settings, clock: Clock, transport: httpx.BaseTransport | None
) -> None:
    """Return once Rancher answers ``/ping`` with ``pong``."""
    deadline = clock.monotonic() + settings.wait_seconds
    with httpx.Client(base_url=rancher_url, transport=transport, timeout=10.0) as client:
        while True:
            try:
                response = client.get("/ping")
                if response.status_code == 200 and response.text.strip() == "pong":
                    return
                last = f"HTTP {response.status_code}"
            except httpx.HTTPError as error:
                last = type(error).__name__
            if clock.monotonic() >= deadline:
                raise ConfigureError(
                    f"Rancher did not answer at {rancher_url} (last answer: {last}). Read the "
                    "host's log with Session Manager: journalctl -t rancher-bootstrap"
                )
            clock.sleep(settings.poll_seconds)


def login(
    rancher_url: str, username: str, password: str, transport: httpx.BaseTransport | None
) -> str:
    """Sign in as a local user and return the session's bearer token."""
    body = {
        "type": "localProvider",
        "username": username,
        "password": password,
        "responseType": "json",
        "description": f"configure_rancher.py session ({username})",
    }
    try:
        with httpx.Client(base_url=rancher_url, transport=transport, timeout=30.0) as client:
            response = client.post("/v1-public/login", json=body)
    except httpx.HTTPError as error:
        raise ConfigureError(f"signing in as {username} failed: {type(error).__name__}") from error
    if response.status_code not in (200, 201):
        raise ConfigureError(
            f"Rancher refused the sign-in as {username} (HTTP {response.status_code})"
        )
    return _text(response.json(), "token")


def end_session(api: RancherAPI, token: str, console: Console) -> None:
    """Log the session out once it is no longer needed.

    Rancher refuses to delete the token of the session that makes the request
    ("Use logout instead"), so the session logs itself out.
    """
    try:
        api.post("/v3/tokens", {}, {"action": "logout"})
    except RancherError as error:
        name = token.split(":", 1)[0]
        console.say(f"Note: could not log out the session {name}; it expires on its own. {error}")


def keep_admin_password(api: RancherAPI, password: str, console: Console) -> None:
    """Clear the change-on-first-login flag by setting the same password.

    Rancher marks a generated admin password as one to change at first login. Kept
    as it is, the password in Secrets Manager stays valid for break-glass use.
    """
    admins = _items(api.get("/v3/users", {"username": "admin"}))
    if len(admins) != 1:
        raise RancherError(f"expected one local admin user, found {len(admins)}")
    if admins[0].get("mustChangePassword"):
        admin_id = _text(admins[0], "id")
        api.post(f"/v3/users/{admin_id}", {"newPassword": password}, {"action": "setpassword"})
        console.say("Admin: kept the generated password as the break-glass password.")


def ensure_setting(api: RancherAPI, name: str, value: str, console: Console) -> None:
    if api.get(f"/v3/settings/{name}").get("value") != value:
        api.put(f"/v3/settings/{name}", {"value": value})
        console.say(f"Setting {name}: set.")


def ensure_cognito_sign_in(
    api: RancherAPI, cognito: CognitoSignIn, rancher_url: str, console: Console
) -> None:
    """Turn on Cognito sign-in for the operator's identity only (REQ-021.1)."""
    current = api.get("/v3/authConfigs/cognito")
    links = current.get("links")
    target = links.get("self") if isinstance(links, dict) else None
    api.put(
        target if isinstance(target, str) and target else "/v3/authConfigs/cognito",
        {
            "type": "cognitoConfig",
            "name": "cognito",
            "enabled": True,
            "accessMode": "required",
            "allowedPrincipalIds": [cognito.principal_id],
            "clientId": cognito.client_id,
            "clientSecret": cognito.client_secret,
            "issuer": cognito.issuer,
            "rancherUrl": f"{rancher_url}/verify-auth",
            "scope": "openid email profile",
            "groupSearchEnabled": False,
            "pkceMethod": "S256",
        },
    )
    console.say("Sign-in: Amazon Cognito, required for the operator identity only.")


def ensure_operator_is_admin(api: RancherAPI, principal_id: str, console: Console) -> None:
    """Make the operator's Cognito identity a Rancher admin, before its first sign-in.

    Rancher's v3 API binds a global role only to an existing user or to a group,
    and the operator has no Rancher user until it signs in. A binding created
    through Rancher's Kubernetes API (/v1) may name the user principal instead:
    Rancher then creates the user for that principal and binds the role to it
    (Rancher 2.15, GlobalRoleBinding.userPrincipalName).
    """
    for binding in _items(api.get(GLOBAL_ROLE_BINDINGS)):
        if (
            binding.get("globalRoleName") == "admin"
            and binding.get("userPrincipalName") == principal_id
        ):
            return
    api.post(
        GLOBAL_ROLE_BINDINGS,
        {
            "type": "management.cattle.io.globalrolebinding",
            "metadata": {"generateName": "grb-"},
            "globalRoleName": "admin",
            "userPrincipalName": principal_id,
        },
    )
    console.say("Sign-in: the operator identity is a Rancher admin.")


def _rule_set(rules: object) -> set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]]:
    """Return rules in a comparable form, ignoring order and empty fields."""
    if not isinstance(rules, list):
        return set()
    return {
        (
            tuple(sorted(rule.get("apiGroups") or [])),
            tuple(sorted(rule.get("resources") or [])),
            tuple(sorted(rule.get("verbs") or [])),
        )
        for rule in rules
        if isinstance(rule, dict)
    }


def ensure_role_template(api: RancherAPI, name: str, console: Console) -> str:
    """Create or correct the read-only cluster role and return its ID (REQ-050.1)."""
    body: JSON = {
        "type": "roleTemplate",
        "name": name,
        "description": "Read-only access for the SRE agent: no Secrets, no write verb (REQ-050.1).",
        "context": "cluster",
        "rules": [dict(rule) for rule in AGENT_READ_RULES],
        "roleTemplateIds": [],
        "administrative": False,
        "clusterCreatorDefault": False,
        "projectCreatorDefault": False,
        "external": False,
        "hidden": False,
        "locked": False,
    }
    found = _items(api.get("/v3/roletemplates", {"name": name}))
    if not found:
        console.say(f"Role {name}: created.")
        return _text(api.post("/v3/roletemplates", body), "id")
    template = found[0]
    template_id = _text(template, "id")
    drifted = _rule_set(template.get("rules")) != _rule_set(list(AGENT_READ_RULES))
    if drifted or template.get("roleTemplateIds") or template.get("context") != "cluster":
        api.put(f"/v3/roletemplates/{template_id}", body)
        console.say(f"Role {name}: corrected to the read-only rules.")
    return template_id


def ensure_agent_user(api: RancherAPI, username: str, password: str, console: Console) -> str:
    """Create the agent's local user, or give it a new password, and return its ID."""
    found = _items(api.get("/v3/users", {"username": username}))
    if not found:
        created = api.post(
            "/v3/users",
            {
                "type": "user",
                "username": username,
                "name": username,
                "description": "The SRE agent's read-only identity (REQ-050.1).",
                "password": password,
                "mustChangePassword": False,
                "enabled": True,
            },
        )
        console.say(f"User {username}: created.")
        return _text(created, "id")
    user_id = _text(found[0], "id")
    api.post(f"/v3/users/{user_id}", {"newPassword": password}, {"action": "setpassword"})
    if found[0].get("enabled") is False:
        api.put(f"/v3/users/{user_id}", {"enabled": True})
    return user_id


def ensure_login_access_only(api: RancherAPI, user_id: str, console: Console) -> None:
    """Leave the user exactly one global role: login access."""
    bindings = _items(api.get("/v3/globalrolebindings", {"userId": user_id}))
    for binding in bindings:
        if binding.get("globalRoleId") != LOGIN_ONLY_GLOBAL_ROLE:
            api.delete(f"/v3/globalrolebindings/{_text(binding, 'id')}")
            console.say(f"User: removed the global role {binding.get('globalRoleId')}.")
    if not any(b.get("globalRoleId") == LOGIN_ONLY_GLOBAL_ROLE for b in bindings):
        api.post(
            "/v3/globalrolebindings",
            {
                "type": "globalRoleBinding",
                "globalRoleId": LOGIN_ONLY_GLOBAL_ROLE,
                "userId": user_id,
            },
        )


def ensure_cluster(api: RancherAPI, name: str, console: Console) -> str:
    """Create the imported cluster record labelled cloud=aws, and return its ID (REQ-022)."""
    found = _items(api.get("/v3/clusters", {"name": name}))
    if not found:
        created = api.post(
            "/v3/clusters",
            {
                "type": "cluster",
                "name": name,
                "description": "The lab's EKS cluster, imported; Fleet targets it by cloud=aws.",
                "labels": {"cloud": "aws"},
            },
        )
        console.say(f"Cluster {name}: created as an imported cluster.")
        return _text(created, "id")
    cluster = found[0]
    cluster_id = _text(cluster, "id")
    found_labels = cluster.get("labels")
    labels: JSON = found_labels if isinstance(found_labels, dict) else {}
    if labels.get("cloud") != "aws":
        api.put(f"/v3/clusters/{cluster_id}", {"labels": {**labels, "cloud": "aws"}})
        console.say(f"Cluster {name}: labelled cloud=aws.")
    return cluster_id


def ensure_cluster_binding(
    api: RancherAPI, cluster_id: str, user_id: str, role_template_id: str, console: Console
) -> None:
    """Bind the user to the cluster with the read-only role, and with nothing else."""
    bindings = _items(
        api.get("/v3/clusterroletemplatebindings", {"clusterId": cluster_id, "userId": user_id})
    )
    for binding in bindings:
        if binding.get("roleTemplateId") != role_template_id:
            api.delete(f"/v3/clusterroletemplatebindings/{_text(binding, 'id')}")
            console.say(f"Cluster: removed the extra role {binding.get('roleTemplateId')}.")
    if not any(b.get("roleTemplateId") == role_template_id for b in bindings):
        api.post(
            "/v3/clusterroletemplatebindings",
            {
                "type": "clusterRoleTemplateBinding",
                "clusterId": cluster_id,
                "userId": user_id,
                "roleTemplateId": role_template_id,
            },
        )


def registration_command(api: RancherAPI, cluster_id: str, settings: Settings, clock: Clock) -> str:
    """Return the cluster's ``kubectl apply`` registration command, creating a token if needed."""
    deadline = clock.monotonic() + settings.wait_seconds
    query = {"clusterId": cluster_id}
    if not _items(api.get("/v3/clusterregistrationtokens", query)):
        api.post(
            "/v3/clusterregistrationtokens",
            {"type": "clusterRegistrationToken", "clusterId": cluster_id},
        )
    while True:
        commands = [
            t.get("command") for t in _items(api.get("/v3/clusterregistrationtokens", query))
        ]
        ready = [command for command in commands if isinstance(command, str) and command]
        if ready:
            return ready[0]
        if clock.monotonic() >= deadline:
            raise ConfigureError("Rancher has not produced a registration command for the cluster")
        clock.sleep(settings.poll_seconds)


def _cluster_ready(cluster: JSON) -> bool:
    """Return True when Rancher reports the cluster's Ready condition as True.

    A cluster record reads "active" for a moment after it is created, before
    Rancher adds any conditions, so its state alone does not show that the
    cluster agent has connected.
    """
    conditions = cluster.get("conditions")
    return isinstance(conditions, list) and any(
        isinstance(c, dict) and c.get("type") == "Ready" and c.get("status") == "True"
        for c in conditions
    )


def ensure_cluster_active(
    api: RancherAPI, cluster_id: str, settings: Settings, clock: Clock, console: Console
) -> None:
    """Print the registration command until Rancher reports the cluster Ready, and wait."""
    if _cluster_ready(api.get(f"/v3/clusters/{cluster_id}")):
        return
    command = registration_command(api, cluster_id, settings, clock)
    console.say(
        "Register the EKS cluster: in a terminal with your admin profile, run\n"
        f"    aws eks update-kubeconfig --region {settings.region} --name {settings.cluster_name}\n"
        f"    {command}\n"
        "Waiting for Rancher to report the cluster Ready..."
    )
    deadline = clock.monotonic() + settings.wait_seconds
    while not _cluster_ready(api.get(f"/v3/clusters/{cluster_id}")):
        if clock.monotonic() >= deadline:
            raise ConfigureError(
                f"the cluster {settings.cluster_name} did not turn Ready. Check that the "
                "registration command ran, and the cattle-system pods on EKS"
            )
        clock.sleep(settings.poll_seconds)
    console.say(f"Cluster {settings.cluster_name}: ready.")


def ensure_gitrepo(api: RancherAPI, settings: Settings, console: Console) -> None:
    """Point Fleet at platform/ on main, for clusters labelled cloud=aws (REQ-022)."""
    if not settings.repo_url.startswith("https://"):
        raise ConfigureError("the repository URL must use HTTPS")
    spec: JSON = {
        "repo": settings.repo_url,
        "branch": settings.branch,
        "paths": [settings.fleet_path],
        "targets": [{"name": "cloud-aws", "clusterSelector": {"matchLabels": {"cloud": "aws"}}}],
    }
    path = f"/v1/fleet.cattle.io.gitrepos/{FLEET_WORKSPACE}/{settings.gitrepo_name}"
    existing = api.get_optional(path)
    if existing is None:
        metadata = {"name": settings.gitrepo_name, "namespace": FLEET_WORKSPACE}
        api.post(
            "/v1/fleet.cattle.io.gitrepos",
            {"type": "fleet.cattle.io.gitrepo", "metadata": metadata, "spec": spec},
        )
        console.say(f"Fleet: GitRepo {settings.gitrepo_name} created.")
        return
    found_spec = existing.get("spec")
    current: JSON = found_spec if isinstance(found_spec, dict) else {}
    if all(current.get(key) == value for key, value in spec.items()) and not current.get(
        "clientSecretName"
    ):
        return
    updated = {key: value for key, value in current.items() if key != "clientSecretName"}
    api.put(path, {**existing, "spec": {**updated, **spec}})
    console.say(f"Fleet: GitRepo {settings.gitrepo_name} corrected.")


def rotate_agent_token(
    rancher_url: str,
    agent_password: str,
    aws: AwsClients,
    settings: Settings,
    console: Console,
    transport: httpx.BaseTransport | None,
) -> None:
    """Issue the agent's 30-day token, store it, then delete the ones earlier runs issued."""
    session = console.secret(login(rancher_url, settings.agent_username, agent_password, transport))
    with RancherAPI(rancher_url, session, console, transport) as agent:
        ttl = settings.token_ttl_days * MILLISECONDS_PER_DAY
        created = agent.post(
            "/v3/tokens",
            {"type": "token", "description": AGENT_CREDENTIAL_DESCRIPTION, "ttl": ttl},
        )
        token = console.secret(_text(created, "token"))
        new_name = token.split(":", 1)[0]
        write_secret(aws.secrets, settings.agent_credential_name, token)
        # Rancher sets expiresAt on a token's first use, so read the stored token
        # back with itself: that shows its expiry and proves it signs in.
        with RancherAPI(rancher_url, token, console, transport) as stored:
            expires = stored.get(f"/v3/tokens/{new_name}").get("expiresAt")
        console.say(
            f"Token: a new {settings.agent_username} token, which signs in and expires "
            f"{expires or f'in {settings.token_ttl_days} days'}, is in "
            f"{settings.agent_credential_name}."
        )
        for old in _items(agent.get("/v3/tokens")):
            name = old.get("name")
            if old.get("description") == AGENT_CREDENTIAL_DESCRIPTION and name != new_name:
                agent.delete(f"/v3/tokens/{name}")
        end_session(agent, session, console)


def configure(
    settings: Settings,
    aws: AwsClients,
    clock: Clock,
    console: Console,
    transport: httpx.BaseTransport | None = None,
) -> None:
    """Run every step in order. Each one is safe to repeat."""
    rancher_url = f"https://rancher.{read_parameter(aws.ssm, settings.domain_parameter)}"
    console.say(f"Waiting for Rancher at {rancher_url} ...")
    wait_for_rancher(rancher_url, settings, clock, transport)
    password = console.secret(
        wait_for_secret(aws.secrets, settings.admin_credential_name, settings, clock)
    )
    admin_session = console.secret(login(rancher_url, "admin", password, transport))
    agent_password = console.secret(secrets.token_urlsafe(32))
    with RancherAPI(rancher_url, admin_session, console, transport) as api:
        keep_admin_password(api, password, console)
        ensure_setting(api, "server-url", rancher_url, console)
        cognito = read_cognito(aws.cognito, settings)
        console.secret(cognito.client_secret)
        ensure_cognito_sign_in(api, cognito, rancher_url, console)
        ensure_operator_is_admin(api, cognito.principal_id, console)
        role_template_id = ensure_role_template(api, settings.role_template_name, console)
        user_id = ensure_agent_user(api, settings.agent_username, agent_password, console)
        ensure_login_access_only(api, user_id, console)
        cluster_id = ensure_cluster(api, settings.cluster_name, console)
        ensure_cluster_binding(api, cluster_id, user_id, role_template_id, console)
        ensure_cluster_active(api, cluster_id, settings, clock, console)
        ensure_gitrepo(api, settings, console)
        rotate_agent_token(rancher_url, agent_password, aws, settings, console, transport)
        end_session(api, admin_session, console)
    console.say("Rancher is configured.")


def parse_args(argv: Sequence[str] | None) -> Settings:
    defaults = Settings()
    parser = argparse.ArgumentParser(
        description="Configure the lab's Rancher: sign-in, the agent's read-only access, "
        "the EKS registration and Fleet. Safe to run again."
    )
    parser.add_argument("--region", default=defaults.region)
    parser.add_argument("--cluster-name", default=defaults.cluster_name)
    parser.add_argument("--repo-url", default=defaults.repo_url, help="public HTTPS Git URL")
    parser.add_argument("--branch", default=defaults.branch)
    parser.add_argument(
        "--wait-minutes",
        type=float,
        default=defaults.wait_seconds / 60,
        help="how long each wait may last (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    return Settings(
        region=args.region,
        cluster_name=args.cluster_name,
        repo_url=args.repo_url,
        branch=args.branch,
        wait_seconds=args.wait_minutes * 60,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    session: boto3.Session | None = None,
    clock: Clock | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """Configure Rancher and return the exit status."""
    settings = parse_args(argv)
    console = Console()
    aws = AwsClients.from_session(session or boto3.Session(region_name=settings.region))
    try:
        configure(settings, aws, clock or Clock(), console, transport)
    except ConfigureError as error:
        console.error(
            f"{error}. Nothing after this step ran; run the script again once it is fixed."
        )
        return 1
    except (BotoCoreError, ClientError) as error:
        console.error(f"an AWS call failed: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
