"""Tests for tools/spikes/spike-a/teardown.py. moto plays EC2, ELBv2, ACM, Route 53, IAM,
SSM and STS; botocore's Stubber, which validates requests and responses against the real
service model, plays bedrock-agentcore-control. Each test first builds the spike's world
with setup_gateway.run(apply=True), then tears it down."""

import datetime
import importlib.util
import io
import os
import re
import sys
from pathlib import Path

os.environ["MOTO_ACM_VALIDATION_WAIT"] = "0"

import boto3
import botocore.waiter
import pytest
from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber
from moto import mock_aws

REPO = Path(__file__).resolve().parents[2]


def _load(name, path):
    loaded = sys.modules.get(name)
    if loaded is not None and Path(loaded.__file__).resolve() == path.resolve():
        return loaded
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sg = _load("setup_gateway", REPO / "tools/spikes/spike-a/setup_gateway.py")
td = _load("teardown", REPO / "tools/spikes/spike-a/teardown.py")

DOMAIN = "example.com"
ACCOUNT = "123456789012"
TOKEN = "token-abcde:Zm9vYmFyYmF6cXV4"  # noqa: S105 - synthetic
NOW = datetime.datetime(2026, 11, 14, tzinfo=datetime.UTC)
GW_ID = "rancher-spike-abcdefghij"
GW_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:gateway/{GW_ID}"
PROVIDER_ARN = (
    f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:"
    "token-vault/default/apikeycredentialprovider/rancher-spike"
)
SECRET_ARN = (
    f"arn:aws:secretsmanager:us-east-1:{ACCOUNT}:secret:"
    "bedrock-agentcore-identity!default/apikey/rancher-spike-AbCdEf"
)


# The world ---------------------------------------------------------------------------


@pytest.fixture
def aws(monkeypatch, tmp_path):
    for name in ("AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setattr(botocore.waiter.time, "sleep", lambda s: None)
    monkeypatch.setattr(sg, "STATE_DIR", tmp_path / "state")
    with mock_aws():
        session = boto3.Session(region_name="us-east-1")
        session.client("ssm").put_parameter(
            Name="/sre-lab/domain-name", Value=DOMAIN, Type="String"
        )
        session.client("route53").create_hosted_zone(Name=DOMAIN, CallerReference="spike")
        ec2 = session.client("ec2")
        vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]
        group = ec2.create_security_group(
            GroupName="rancher-spike", Description="spike", VpcId=vpc["VpcId"]
        )["GroupId"]
        subnet = next(
            s
            for s in ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}])[
                "Subnets"
            ]
            if s["AvailabilityZoneId"] == "use1-az6"
        )
        ec2.run_instances(
            ImageId="ami-12c6146b",
            MinCount=1,
            MaxCount=1,
            InstanceType="t3.large",
            SubnetId=subnet["SubnetId"],
            SecurityGroupIds=[group],
            TagSpecifications=[
                {"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": "rancher-spike"}]}
            ],
        )
        ec2.create_key_pair(KeyName="rancher-spike", KeyType="ed25519")
        yield session


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def monotonic(self):
        return self.now


def gateway(status="READY"):
    return {
        "gatewayArn": GW_ARN,
        "gatewayId": GW_ID,
        "gatewayUrl": f"https://{GW_ID}.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "createdAt": NOW,
        "updatedAt": NOW,
        "status": status,
        "name": "rancher-spike",
        "authorizerType": "AWS_IAM",
    }


def target(status="READY"):
    return {
        "gatewayArn": GW_ARN,
        "targetId": "TARGET1234",
        "createdAt": NOW,
        "updatedAt": NOW,
        "status": status,
        "name": "rancher",
        "targetConfiguration": {
            "mcp": {"mcpServer": {"endpoint": f"https://mcp-spike.{DOMAIN}/mcp"}}
        },
        "credentialProviderConfigurations": [{"credentialProviderType": "API_KEY"}],
    }


def provider(full=False):
    found = {
        "apiKeySecretArn": {"secretArn": SECRET_ARN},
        "name": "rancher-spike",
        "credentialProviderArn": PROVIDER_ARN,
    }
    return {**found, "createdTime": NOW, "lastUpdatedTime": NOW} if full else found


GATEWAY_SUMMARY = {
    "gatewayId": GW_ID,
    "name": "rancher-spike",
    "status": "READY",
    "createdAt": NOW,
    "updatedAt": NOW,
    "authorizerType": "AWS_IAM",
}
TARGET_SUMMARY = {
    "targetId": "TARGET1234",
    "name": "rancher",
    "status": "READY",
    "createdAt": NOW,
    "updatedAt": NOW,
}


def setup_stubs(stubber):
    stubber.add_client_error(
        "get_api_key_credential_provider",
        service_error_code="ResourceNotFoundException",
        http_status_code=404,
    )
    stubber.add_response(
        "create_api_key_credential_provider",
        provider(),
        {"name": "rancher-spike", "apiKey": TOKEN, "tags": ANY},
    )
    stubber.add_response("list_gateways", {"items": []}, {})
    stubber.add_response("create_gateway", gateway("READY"), None)
    stubber.add_response("get_gateway", gateway("READY"), {"gatewayIdentifier": GW_ID})
    stubber.add_response("list_gateway_targets", {"items": []}, {"gatewayIdentifier": GW_ID})
    stubber.add_response("create_gateway_target", target("CREATING"), None)
    stubber.add_response(
        "get_gateway_target",
        target("READY"),
        {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )


def plan_stubs(stubber):
    stubber.add_response("list_gateways", {"items": [GATEWAY_SUMMARY]}, {})
    stubber.add_response(
        "list_gateway_targets", {"items": [TARGET_SUMMARY]}, {"gatewayIdentifier": GW_ID}
    )
    stubber.add_response(
        "get_api_key_credential_provider", provider(full=True), {"name": "rancher-spike"}
    )


def apply_stubs(stubber):
    stubber.add_response("list_gateways", {"items": [GATEWAY_SUMMARY]}, {})
    stubber.add_response(
        "list_gateway_targets", {"items": [TARGET_SUMMARY]}, {"gatewayIdentifier": GW_ID}
    )
    stubber.add_response(
        "delete_gateway_target",
        {"gatewayArn": GW_ARN, "targetId": "TARGET1234", "status": "DELETING"},
        {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )
    stubber.add_response(
        "get_gateway_target",
        target("DELETING"),
        {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )
    stubber.add_client_error(
        "get_gateway_target",
        service_error_code="ResourceNotFoundException",
        http_status_code=404,
        expected_params={"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )
    stubber.add_response(
        "delete_gateway", {"gatewayId": GW_ID, "status": "DELETING"}, {"gatewayIdentifier": GW_ID}
    )
    stubber.add_response("get_gateway", gateway("DELETING"), {"gatewayIdentifier": GW_ID})
    stubber.add_client_error(
        "get_gateway",
        service_error_code="ResourceNotFoundException",
        http_status_code=404,
        expected_params={"gatewayIdentifier": GW_ID},
    )
    stubber.add_response(
        "get_api_key_credential_provider", provider(full=True), {"name": "rancher-spike"}
    )
    stubber.add_response("delete_api_key_credential_provider", {}, {"name": "rancher-spike"})


def nothing_left_stubs(stubber):
    stubber.add_response("list_gateways", {"items": []}, {})
    stubber.add_client_error(
        "get_api_key_credential_provider",
        service_error_code="ResourceNotFoundException",
        http_status_code=404,
        expected_params={"name": "rancher-spike"},
    )


def clients_with(session, stubs):
    agentcore = session.client("bedrock-agentcore-control")
    stubber = Stubber(agentcore)
    stubs(stubber)
    stubber.activate()
    clients = sg.Clients.from_session(session)
    return sg.Clients(**{**clients.__dict__, "agentcore": agentcore}), stubber


class Local:
    """The Mac side: Keychain, files, Docker image and SSH, all fake."""

    def __init__(self, tmp_path):
        self.keychain = {"admin", "sre-agent", "sre-agent-token"}
        self.image = True
        self.remote = []
        self.clock = Clock()
        self.paths = td.Paths(
            home=tmp_path,
            state_dir=tmp_path / "state",
            ssh_key=tmp_path / ".ssh" / "rancher-spike.pem",
        )

    def seams(self):
        def delete(account):
            present = account in self.keychain
            self.keychain.discard(account)
            return present

        def remove_image():
            self.image = False
            return True

        return td.Seams(
            run_on_instance=lambda ip, script: self.remote.append(script) or "removed\n",
            keychain_has=lambda account: account in self.keychain,
            delete_keychain_item=delete,
            image_present=lambda: self.image,
            remove_image=remove_image,
            sleep=self.clock.sleep,
            monotonic=self.clock.monotonic,
        )


def build_spike(session, tmp_path):
    clients, stubber = clients_with(session, setup_stubs)
    clock = Clock()
    seams = sg.Seams(
        keychain_token=lambda: TOKEN,
        run_on_instance=lambda ip, script: "mcp-http-status=400\n",
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )
    out = sg.Out(stream=io.StringIO())
    assert sg.run(clients, seams, out, apply=True) == 0, out.stream.getvalue()
    stubber.assert_no_pending_responses()
    # moto issues the certificate at once, so setup skipped the validation record that real
    # ACM needs; add it, as a pending certificate's apply would have.
    acm = session.client("acm")
    arn = acm.list_certificates()["CertificateSummaryList"][0]["CertificateArn"]
    record = acm.describe_certificate(CertificateArn=arn)["Certificate"]["DomainValidationOptions"][
        0
    ]["ResourceRecord"]
    route53 = session.client("route53")
    zone = route53.list_hosted_zones_by_name(DNSName=DOMAIN)["HostedZones"][0]["Id"]
    route53.change_resource_record_sets(
        HostedZoneId=zone,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": record["Name"],
                        "Type": record["Type"],
                        "TTL": 300,
                        "ResourceRecords": [{"Value": record["Value"]}],
                    },
                }
            ]
        },
    )
    local = Local(tmp_path)
    local.paths.state_dir.mkdir(parents=True, exist_ok=True)
    for name in ("rancher-url", "rancher-ca.pem", "known_hosts"):
        (local.paths.state_dir / name).write_text("x\n")
    local.paths.ssh_key.parent.mkdir(parents=True, exist_ok=True)
    local.paths.ssh_key.write_text("key\n")
    assert (local.paths.state_dir / "gateway.json").exists()
    return local


def teardown(session, local, stubs, apply, keep_instance=False):
    clients, stubber = clients_with(session, stubs)
    stream = io.StringIO()
    code = td.run(clients, local.seams(), local.paths, sg.Out(stream=stream), apply, keep_instance)
    stubber.assert_no_pending_responses()
    return code, stream.getvalue()


def spike_state(session):
    ec2 = session.client("ec2")
    elb = session.client("elbv2")
    vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    groups = [g["GroupName"] for g in ec2.describe_security_groups()["SecurityGroups"]]
    instances = [
        (i["InstanceId"], i["State"]["Name"])
        for r in ec2.describe_instances(
            Filters=[{"Name": "tag:Name", "Values": ["rancher-spike"]}]
        )["Reservations"]
        for i in r["Instances"]
    ]
    try:
        role = session.client("iam").get_role(RoleName="rancher-spike-gateway")["Role"]["RoleName"]
    except ClientError:
        role = None
    zone = session.client("route53").list_hosted_zones_by_name(DNSName=DOMAIN)["HostedZones"][0][
        "Id"
    ]
    cnames = [
        r
        for r in session.client("route53").list_resource_record_sets(HostedZoneId=zone)[
            "ResourceRecordSets"
        ]
        if r["Type"] == "CNAME"
    ]
    try:
        key_pairs = [
            k["KeyName"] for k in ec2.describe_key_pairs(KeyNames=["rancher-spike"])["KeyPairs"]
        ]
    except ClientError:
        key_pairs = []
    return {
        "default_vpc": bool(vpcs),
        "albs": [lb["LoadBalancerName"] for lb in elb.describe_load_balancers()["LoadBalancers"]],
        "target_groups": [
            t["TargetGroupName"] for t in elb.describe_target_groups()["TargetGroups"]
        ],
        "groups": sorted(g for g in groups if g != "default"),
        "instances": instances,
        "certificates": [
            c["DomainName"]
            for c in session.client("acm").list_certificates()["CertificateSummaryList"]
        ],
        "role": role,
        "cnames": len(cnames),
        "key_pairs": key_pairs,
    }


def assert_private_values_hidden(printed):
    for private in (DOMAIN, ACCOUNT, TOKEN):
        assert private not in printed, private


# Tests -------------------------------------------------------------------------------


def test_plan_lists_everything_and_deletes_nothing(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    before = spike_state(aws)
    code, printed = teardown(aws, local, plan_stubs, apply=False)
    assert code == 0, printed
    lines = printed.splitlines()
    todo = [
        line for line in lines if line.startswith(("To delete:", "To remove:", "To terminate:"))
    ]
    assert lines[-1] == f"Teardown plan: {len(todo)} to delete."
    for expected in (
        "To delete: AgentCore target rancher (READY) and its private endpoint.",
        "To delete: AgentCore gateway rancher-spike.",
        "To delete: credential provider rancher-spike and its secret.",
        "To delete: IAM role rancher-spike-gateway and its inline policy.",
        "To delete: HTTPS listener on 443.",
        "To delete: internal load balancer mcp-spike.",
        "To delete: target group mcp-spike.",
        "To remove: port 9092 rule on security group rancher-spike, from mcp-spike-alb.",
        "To delete: security group mcp-spike-alb.",
        "To delete: security group mcp-spike-gateway.",
        "To delete: ACM certificate for mcp-spike.<domain>.",
        "To delete: its DNS validation record in the public zone.",
        "To delete: security group rancher-spike.",
        "To delete: key pair rancher-spike.",
        "To delete: Keychain item rancher-spike / sre-agent-token.",
        "To delete: ~/.rancher-spike/gateway.json."
        if False
        else "To delete: ~/state/gateway.json.",
        "To delete: ~/.ssh/rancher-spike.pem.",
        "To delete: local Docker image rancher-ai-mcp:v1.2.0-alpha.5.",
    ):
        assert expected in lines, expected
    assert any(line.startswith("To terminate: instance i-") for line in lines)
    # moto's default VPC has no internet gateway; a real one has one.
    assert any(
        re.match(
            r"To delete: default VPC 172\.31\.0\.0/16 with \d internet gateway\(s\) and 6 subnets",
            line,
        )
        for line in lines
    )
    assert spike_state(aws) == before
    assert local.keychain == {"admin", "sre-agent", "sre-agent-token"}
    assert local.image
    assert (local.paths.state_dir / "gateway.json").exists()
    assert local.paths.ssh_key.exists()
    assert local.remote == []
    assert_private_values_hidden(printed)


def test_apply_removes_everything_and_a_second_apply_finds_nothing(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    code, printed = teardown(aws, local, apply_stubs, apply=True)
    assert code == 0, printed
    assert printed.splitlines()[-1].startswith(
        "Teardown complete: nothing the spike created is left"
    )
    state = spike_state(aws)
    assert state["default_vpc"] is False
    assert state["albs"] == []
    assert state["target_groups"] == []
    assert state["groups"] == []
    assert all(status == "terminated" for _, status in state["instances"])
    assert state["certificates"] == []
    assert state["cnames"] == 0
    assert state["role"] is None
    assert state["key_pairs"] == []
    assert local.keychain == set()
    assert local.image is False
    assert not local.paths.state_dir.exists()
    assert not local.paths.ssh_key.exists()
    assert_private_values_hidden(printed)

    code, again = teardown(aws, local, nothing_left_stubs, apply=True)
    assert code == 0, again
    assert [
        line for line in again.splitlines() if line.startswith(("Deleted", "Removed", "Terminated"))
    ] == []
    assert "(0 actions)" in again.splitlines()[-1]

    code, plan = teardown(aws, local, nothing_left_stubs, apply=False)
    assert plan.splitlines()[-1] == "Teardown plan: 0 to delete."


def test_keep_instance_removes_only_a5(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    instance_before = spike_state(aws)["instances"]
    code, printed = teardown(aws, local, apply_stubs, apply=True, keep_instance=True)
    assert code == 0, printed
    assert "the instance and the rest of A1 to A4 remain" in printed.splitlines()[-1]
    state = spike_state(aws)
    assert state["instances"] == instance_before
    assert instance_before[0][1] == "running"
    assert state["default_vpc"] is True
    assert state["groups"] == ["rancher-spike"]
    assert state["key_pairs"] == ["rancher-spike"]
    assert state["albs"] == []
    assert state["target_groups"] == []
    assert state["certificates"] == []
    assert state["role"] is None
    assert state["cnames"] == 0
    ec2 = aws.client("ec2")
    group = ec2.describe_security_groups(
        Filters=[{"Name": "group-name", "Values": ["rancher-spike"]}]
    )["SecurityGroups"][0]
    assert not any(rule.get("FromPort") == 9092 for rule in group["IpPermissions"])
    assert local.remote == [td.REMOTE_REMOVE]
    assert local.keychain == {"admin", "sre-agent", "sre-agent-token"}
    assert local.image
    assert local.paths.ssh_key.exists()
    assert (local.paths.state_dir / "rancher-ca.pem").exists()
    assert_private_values_hidden(printed)


def test_the_default_vpc_stays_while_another_instance_runs_in_it(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    ec2 = aws.client("ec2")
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]
    subnet = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}])[
        "Subnets"
    ][0]
    ec2.run_instances(
        ImageId="ami-12c6146b",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        SubnetId=subnet["SubnetId"],
    )

    _code, plan = teardown(aws, local, plan_stubs, apply=False)
    assert "Default VPC: kept, because it has 1 other instance(s)." in plan
    assert not any(line.startswith("To delete: default VPC") for line in plan.splitlines())

    clients, _stubber = clients_with(aws, apply_stubs)
    stream = io.StringIO()
    with pytest.raises(td.TeardownError, match="the default VPC still has 1 other instance"):
        td.run(clients, local.seams(), local.paths, sg.Out(stream=stream), True, False)
    state = spike_state(aws)
    assert state["default_vpc"] is True
    assert all(status == "terminated" for _, status in state["instances"])
    assert state["albs"] == []
    assert state["certificates"] == []


def test_the_certificate_goes_only_after_the_load_balancer(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    clients, _stubber = clients_with(aws, apply_stubs)
    seen = []

    def check(**kwargs):
        try:
            clients.elbv2.describe_load_balancers(Names=["mcp-spike"])
            seen.append("load balancer still there")
        except ClientError as error:
            seen.append(error.response["Error"]["Code"])

    clients.acm.meta.events.register("before-call.acm.DeleteCertificate", check)
    stream = io.StringIO()
    assert td.run(clients, local.seams(), local.paths, sg.Out(stream=stream), True, False) == 0, (
        stream.getvalue()
    )
    assert seen == ["LoadBalancerNotFound"]
    printed = stream.getvalue().splitlines()
    assert printed.index("Deleted: internal load balancer mcp-spike.") < printed.index(
        "Deleted: ACM certificate for mcp-spike.<domain>."
    )


def test_a_lingering_security_group_is_retried_then_deleted(aws, tmp_path):
    local = build_spike(aws, tmp_path)
    clients, _stubber = clients_with(aws, apply_stubs)
    real_delete = clients.ec2.delete_security_group
    attempts = {"n": 0}

    def flaky(**kwargs):
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise ClientError(
                {
                    "Error": {
                        "Code": "DependencyViolation",
                        "Message": "resource has a dependent object",
                    }
                },
                "DeleteSecurityGroup",
            )
        return real_delete(**kwargs)

    clients.ec2.delete_security_group = flaky
    stream = io.StringIO()
    assert td.run(clients, local.seams(), local.paths, sg.Out(stream=stream), True, True) == 0, (
        stream.getvalue()
    )
    assert (
        "Security group mcp-spike-alb: AWS still holds it (DependencyViolation); waiting ..."
        in stream.getvalue()
    )
    assert local.clock.now >= 40


def test_read_only_credentials_that_cannot_read_agentcore_still_plan(aws, tmp_path):
    local = build_spike(aws, tmp_path)

    def denied(stubber):
        stubber.add_client_error(
            "list_gateways", service_error_code="AccessDeniedException", http_status_code=403
        )

    code, printed = teardown(aws, local, denied, apply=False)
    assert code == 0
    assert "AgentCore: these credentials cannot read it here; apply checks it." in printed
    assert "To delete: IAM role rancher-spike-gateway and its inline policy." in printed


def test_main_rejects_unknown_modes():
    with pytest.raises(SystemExit) as raised:
        td.main(["destroy"])
    assert raised.value.code == 2
