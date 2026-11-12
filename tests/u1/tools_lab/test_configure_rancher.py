"""Tests of tools/lab/configure_rancher.py (plan Step 11).

AWS is moto and Rancher is the in-memory FakeRancher from conftest.py, so no test
reaches a network. Every secret is generated per test, and each test checks the
state the script leaves behind, not only its exit status.
"""

import secrets
from types import ModuleType
from typing import Any

import pytest

AGENT_CREDENTIAL = "sre-lab/rancher-agent-token"
ADMIN_CREDENTIAL = "sre-lab/rancher-admin-password"
READ_VERBS = {"get", "list", "watch"}
AGENT_RESOURCES = {
    "pods",
    "pods/log",
    "events",
    "namespaces",
    "deployments",
    "replicasets",
    "services",
    "nodes",
}
CREATING_PATHS = {
    "/v3/users",
    "/v3/roletemplates",
    "/v3/globalrolebindings",
    "/v1/management.cattle.io.globalrolebindings",
    "/v3/clusters",
    "/v3/clusterroletemplatebindings",
    "/v3/clusterregistrationtokens",
    "/v1/fleet.cattle.io.gitrepos",
}


def run(script: ModuleType, lab_aws: Any, rancher: Any, clock: tuple[Any, Any]) -> int:
    """Run the script's main() against the fake account and the fake Rancher."""
    return int(
        script.main([], session=lab_aws.session, clock=clock[1], transport=rancher.transport())
    )


def secrets_in_play(lab_aws: Any, rancher: Any) -> list[str]:
    """Every secret value the run handled: passwords, the client secret, all bearers and keys."""
    values = [lab_aws.admin_password, lab_aws.client_secret, *rancher.passwords.values()]
    for bearer in rancher.issued_bearers:
        values += [bearer, bearer.split(":", 1)[1]]
    return values


def test_req_022_second_run_creates_nothing_and_only_rotates_the_token(
    configure_rancher: ModuleType, lab_aws: Any, rancher: Any, clock: tuple[Any, Any]
) -> None:
    """REQ-022, REQ-050.1: the script is idempotent.

    The first run creates the role, user, bindings, cluster record and GitRepo
    once. The second run creates none of them again and corrects nothing; it
    only issues a new agent token and deletes the one before it.
    """
    assert run(configure_rancher, lab_aws, rancher, clock) == 0
    first = len(rancher.calls)
    counts = {
        "users": len(rancher.users),
        "roletemplates": len(rancher.roletemplates),
        "globalrolebindings": len(rancher.globalrolebindings),
        "clusters": len(rancher.clusters),
        "crtbs": len(rancher.crtbs),
        "registration_tokens": len(rancher.registration_tokens),
        "gitrepos": len(rancher.gitrepos),
    }
    first_token = lab_aws.secret_value(AGENT_CREDENTIAL)

    assert run(configure_rancher, lab_aws, rancher, clock) == 0

    assert counts == {
        "users": 3,
        "roletemplates": 1,
        "globalrolebindings": 2,
        "clusters": 1,
        "crtbs": 1,
        "registration_tokens": 1,
        "gitrepos": 1,
    }
    assert counts["users"] == len(rancher.users)
    assert counts["roletemplates"] == len(rancher.roletemplates)
    assert counts["globalrolebindings"] == len(rancher.globalrolebindings)
    assert counts["crtbs"] == len(rancher.crtbs)
    assert counts["gitrepos"] == len(rancher.gitrepos)
    second_writes = [call for call in rancher.calls[first:] if call[0] != "GET"]
    assert not [call for call in second_writes if call[0] == "POST" and call[1] in CREATING_PATHS]
    assert not [call for call in second_writes if call[0] == "PUT" and "roletemplates" in call[1]]
    assert not [call for call in second_writes if call[0] == "PUT" and "gitrepos" in call[1]]
    agent_tokens = rancher.api_tokens_of("sre-agent")
    assert len(agent_tokens) == 1
    newest = f"{agent_tokens[0]['name']}:{agent_tokens[0]['key']}"
    assert lab_aws.secret_value(AGENT_CREDENTIAL) == newest != first_token


def test_req_103_agent_token_is_stored_with_30_day_expiry_and_never_printed(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-103.1, REQ-050.1: the sre-agent token lands in its Secrets Manager secret.

    It expires in 30 days, the sessions the script opened are deleted, and no
    password, client secret, token or token key appears in anything it prints.
    """
    assert run(configure_rancher, lab_aws, rancher, clock) == 0
    out, err = capsys.readouterr()

    agent_tokens = rancher.api_tokens_of("sre-agent")
    assert len(agent_tokens) == 1
    assert agent_tokens[0]["ttl"] == 30 * 86_400_000
    stored = lab_aws.secret_value(AGENT_CREDENTIAL)
    assert stored == f"{agent_tokens[0]['name']}:{agent_tokens[0]['key']}"
    assert not [token for token in rancher.tokens.values() if token["kind"] == "session"]
    for value in secrets_in_play(lab_aws, rancher):
        assert value not in out
        assert value not in err
    assert "Rancher is configured." in out


def test_req_050_agent_role_reads_only_and_never_touches_secrets(
    configure_rancher: ModuleType, lab_aws: Any, rancher: Any, clock: tuple[Any, Any]
) -> None:
    """REQ-050.1: the agent-readonly role holds get, list and watch only, and no Secrets.

    A role, a global role and a cluster binding that grant more (left by hand,
    for example) are corrected: the role gets the read rules back, and the
    agent keeps only login access and the read-only cluster binding.
    """
    rancher.roletemplates["rt-old"] = {
        "id": "rt-old",
        "name": "agent-readonly",
        "context": "cluster",
        "roleTemplateIds": ["cluster-owner"],
        "rules": [{"apiGroups": ["*"], "resources": ["secrets", "pods"], "verbs": ["*"]}],
    }
    rancher.users["u-agent"] = {"id": "u-agent", "username": "sre-agent", "enabled": True}
    rancher.passwords["sre-agent"] = secrets.token_urlsafe(16)
    rancher.globalrolebindings["grb-old"] = {
        "id": "grb-old",
        "globalRoleId": "user",
        "userId": "u-agent",
    }
    rancher.clusters["c-lab"] = {
        "id": "c-lab",
        "name": "sre-lab-eks",
        "labels": {"cloud": "aws"},
        "state": "active",
    }
    rancher.crtbs["crtb-old"] = {
        "id": "crtb-old",
        "clusterId": "c-lab",
        "userId": "u-agent",
        "roleTemplateId": "cluster-owner",
    }

    assert run(configure_rancher, lab_aws, rancher, clock) == 0

    role = rancher.roletemplates["rt-old"]
    assert role["context"] == "cluster"
    assert role["roleTemplateIds"] == []
    granted: set[str] = set()
    for rule in role["rules"]:
        assert set(rule["verbs"]) == READ_VERBS
        assert "*" not in rule["apiGroups"]
        assert "*" not in rule["resources"]
        assert "secrets" not in rule["resources"]
        granted |= set(rule["resources"])
    assert granted == AGENT_RESOURCES
    agent_roles = [
        g["globalRoleId"]
        for g in rancher.globalrolebindings.values()
        if g.get("userId") == "u-agent"
    ]
    assert agent_roles == ["user-base"]
    agent_bindings = [c for c in rancher.crtbs.values() if c["userId"] == "u-agent"]
    assert [(c["clusterId"], c["roleTemplateId"]) for c in agent_bindings] == [("c-lab", "rt-old")]


def test_req_022_fleet_reads_platform_on_main_for_clusters_labelled_cloud_aws(
    configure_rancher: ModuleType, lab_aws: Any, rancher: Any, clock: tuple[Any, Any]
) -> None:
    """REQ-022: Fleet deploys from platform/ on main to clusters labelled cloud=aws.

    The repository is read over HTTPS with no credentials (the repository is
    public, so there is no deploy key). A cluster record without the label, and
    a GitRepo pointing elsewhere or holding a credential, are corrected.
    """
    rancher.clusters["c-lab"] = {
        "id": "c-lab",
        "name": "sre-lab-eks",
        "labels": {},
        "state": "active",
    }
    rancher.gitrepos["fleet-default/sre-lab-platform"] = {
        "id": "fleet-default/sre-lab-platform",
        "metadata": {
            "name": "sre-lab-platform",
            "namespace": "fleet-default",
            "resourceVersion": "7",
        },
        "spec": {
            "repo": "git@github.com:someone/elsewhere.git",
            "branch": "develop",
            "paths": ["other"],
            "clientSecretName": "deploy-key",
        },
    }

    assert run(configure_rancher, lab_aws, rancher, clock) == 0

    assert rancher.clusters["c-lab"]["labels"] == {"cloud": "aws"}
    gitrepo = rancher.gitrepos["fleet-default/sre-lab-platform"]
    assert gitrepo["metadata"]["namespace"] == "fleet-default"
    assert gitrepo["metadata"]["resourceVersion"] == "7"
    spec = gitrepo["spec"]
    assert spec["repo"] == "https://github.com/andrefellipe/multi-cloud-agentic-sre"
    assert spec["branch"] == "main"
    assert spec["paths"] == ["platform"]
    assert [t["clusterSelector"] for t in spec["targets"]] == [{"matchLabels": {"cloud": "aws"}}]
    assert "clientSecretName" not in spec


def test_req_021_cognito_sign_in_needs_mfa_and_admits_only_the_operator(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-021.1: Rancher signs in through Cognito only when the pool requires MFA.

    With MFA off, the script stops and leaves sign-in untouched. With MFA on, it
    enables Cognito for the operator's identity alone, makes that identity an
    admin once, and keeps the local admin password valid for break-glass use.
    """
    lab_aws.set_mfa("OFF")
    assert run(configure_rancher, lab_aws, rancher, clock) == 1
    assert "does not require MFA" in capsys.readouterr().err
    assert rancher.authconfig["enabled"] is False
    assert ("PUT", "/v3/cognitoConfigs/cognito") not in rancher.calls

    lab_aws.set_mfa("ON")
    assert run(configure_rancher, lab_aws, rancher, clock) == 0

    principal = f"cognito_user://{lab_aws.operator_sub}"
    config = rancher.authconfig
    assert config["enabled"] is True
    assert config["accessMode"] == "required"
    assert config["allowedPrincipalIds"] == [principal]
    assert config["clientSecret"] == lab_aws.client_secret
    assert config["issuer"] == f"https://cognito-idp.us-east-1.amazonaws.com/{lab_aws.user_pool_id}"
    assert config["rancherUrl"] == "https://rancher.example.com/verify-auth"
    assert config["pkceMethod"] == "S256"
    operators = [uid for uid, u in rancher.users.items() if principal in u.get("principalIds", [])]
    assert len(operators) == 1
    admins = [g for g in rancher.globalrolebindings.values() if g["globalRoleId"] == "admin"]
    assert [(g.get("userPrincipalId"), g.get("userId")) for g in admins] == [
        (principal, operators[0])
    ]
    assert ("POST", "/v1/management.cattle.io.globalrolebindings") in rancher.calls
    assert rancher.passwords["admin"] == lab_aws.admin_password
    assert rancher.users["user-admin"]["mustChangePassword"] is False
    assert rancher.settings["server-url"] == "https://rancher.example.com"


def test_req_021_operator_who_already_signed_in_is_made_admin_without_a_second_user(
    configure_rancher: ModuleType, lab_aws: Any, rancher: Any, clock: tuple[Any, Any]
) -> None:
    """REQ-021.1: an operator who signed in once before the script ran keeps one user.

    Rancher created that user at the first sign-in, as a standard user. The
    script binds the admin role to the same principal, so Rancher binds it to
    that user and creates no second one.
    """
    principal = f"cognito_user://{lab_aws.operator_sub}"
    rancher.users["u-operator"] = {
        "id": "u-operator",
        "type": "user",
        "principalIds": [principal, "local://u-operator"],
        "enabled": True,
    }

    assert run(configure_rancher, lab_aws, rancher, clock) == 0

    assert [uid for uid, u in rancher.users.items() if principal in u.get("principalIds", [])] == [
        "u-operator"
    ]
    admins = [g for g in rancher.globalrolebindings.values() if g["globalRoleId"] == "admin"]
    assert [g.get("userId") for g in admins] == ["u-operator"]


def test_req_021_v3_refusal_of_the_admin_binding_stops_the_run(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-021.1: when Rancher refuses the admin binding, the script stops and says why.

    Nothing after the binding runs: no agent user, no cluster record, no token.
    """
    rancher.refuse_global_role_bindings = True

    assert run(configure_rancher, lab_aws, rancher, clock) == 1

    err = capsys.readouterr().err
    assert "POST /v1/management.cattle.io.globalrolebindings failed: HTTP 422" in err
    assert "Nothing after this step ran" in err
    assert not [u for u in rancher.users.values() if u.get("username") == "sre-agent"]
    assert not rancher.clusters
    assert lab_aws.secret_value(AGENT_CREDENTIAL) is None


def test_rancher_that_never_answers_fails_without_any_write(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Failure path (plan Step 11): Rancher never answers /ping.

    The script waits its full limit, then stops with a pointer to the host's
    boot log, having signed in nowhere and written nothing.
    """
    rancher.ready = False

    assert run(configure_rancher, lab_aws, rancher, clock) == 1

    assert "did not answer" in capsys.readouterr().err
    assert rancher.writes() == []
    assert clock[0].now >= 1800
    assert lab_aws.secret_value(AGENT_CREDENTIAL) is None


def test_req_021_admin_secret_without_value_stops_before_signing_in(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-021.1: the admin password comes only from the secret the Rancher host wrote.

    While that secret has no value, the script waits, then stops and names the
    secret. It never tries another password and never signs in.
    """
    client = lab_aws.session.client("secretsmanager")
    client.delete_secret(SecretId=ADMIN_CREDENTIAL, ForceDeleteWithoutRecovery=True)
    client.create_secret(Name=ADMIN_CREDENTIAL)

    assert run(configure_rancher, lab_aws, rancher, clock) == 1

    assert f"the secret {ADMIN_CREDENTIAL} still has no value" in capsys.readouterr().err
    assert {path for _, path in rancher.calls} == {"/ping"}


def test_req_103_refused_admin_sign_in_fails_without_writes_or_leaks(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-103.1: when Rancher refuses the admin sign-in, the script stops cleanly.

    It reports the refusal without the password, and changes nothing in Rancher
    or in the agent's token store.
    """
    rancher.reject_logins = True

    assert run(configure_rancher, lab_aws, rancher, clock) == 1

    out, err = capsys.readouterr()
    assert "refused the sign-in as admin" in err
    assert lab_aws.admin_password not in out + err
    assert rancher.writes() == [("POST", "/v1-public/login")]
    assert lab_aws.secret_value(AGENT_CREDENTIAL) is None


def test_req_050_cluster_that_never_turns_active_gets_no_agent_token(
    configure_rancher: ModuleType,
    lab_aws: Any,
    rancher: Any,
    clock: tuple[Any, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """REQ-050.1: no agent token is issued until the cluster it reads is registered.

    The script prints the one registration command for you to run against EKS,
    waits its full limit, then stops. It made no write to EKS itself.
    """
    rancher.polls_until_active = None

    assert run(configure_rancher, lab_aws, rancher, clock) == 1

    out, err = capsys.readouterr()
    assert out.count("kubectl apply -f https://rancher.example.com/v3/import/") == 1
    assert "did not turn active" in err
    assert rancher.api_tokens_of("sre-agent") == []
    assert lab_aws.secret_value(AGENT_CREDENTIAL) is None
