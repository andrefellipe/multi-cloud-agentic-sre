"""Tests for tools/spikes/spike-a/setup_gateway.py: moto for EC2, ELBv2, ACM, Route 53, IAM,
SSM and STS; botocore's Stubber, which validates every request and response against the real
service model, for bedrock-agentcore-control."""

import datetime
import importlib.util
import io
import json
import os
import sys
from pathlib import Path

os.environ["MOTO_ACM_VALIDATION_WAIT"] = "0"

import boto3
import botocore.waiter
import pytest
from botocore.stub import ANY, Stubber
from moto import mock_aws

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "setup_gateway", REPO / "tools/spikes/spike-a/setup_gateway.py"
)
sg = importlib.util.module_from_spec(spec)
sys.modules["setup_gateway"] = sg
spec.loader.exec_module(sg)

DOMAIN = "example.com"
TOKEN = "token-abcde:Zm9vYmFyYmF6cXV4"  # noqa: S105 - synthetic
NOW = datetime.datetime(2026, 11, 14, tzinfo=datetime.UTC)
GW_ID = "rancher-spike-abcdefghij"
GW_ARN = f"arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/{GW_ID}"
PROVIDER_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:123456789012:"
    "token-vault/default/apikeycredentialprovider/rancher-spike"
)
SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:"  # noqa: S105 - an ARN
    "bedrock-agentcore-identity!default/apikey/rancher-spike-AbCdEf"
)


INSTANCE_ZONE = "use1-az3"


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
            if s["AvailabilityZoneId"] == INSTANCE_ZONE
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
        yield session


def make(session, agentcore_stub_setup):
    clients = sg.Clients.from_session(session)
    agentcore = session.client("bedrock-agentcore-control")
    stubber = Stubber(agentcore)
    agentcore_stub_setup(stubber)
    stubber.activate()
    clients = sg.Clients(**{**clients.__dict__, "agentcore": agentcore})
    remote = []
    clock = {"now": 0.0}

    def sleep(seconds):
        clock["now"] += seconds

    seams = sg.Seams(
        keychain_token=lambda: TOKEN,
        run_on_instance=lambda ip, script: remote.append((ip, script)) or "mcp-http-status=400\n",
        sleep=sleep,
        monotonic=lambda: clock["now"],
    )
    stream = io.StringIO()
    return clients, seams, sg.Out(stream=stream), stream, stubber, remote


def provider_response():
    return {
        "apiKeySecretArn": {"secretArn": SECRET_ARN},
        "name": "rancher-spike",
        "credentialProviderArn": PROVIDER_ARN,
    }


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


def fresh_agentcore(stubber, expect):
    stubber.add_client_error(
        "get_api_key_credential_provider",
        service_error_code="ResourceNotFoundException",
        http_status_code=404,
        expected_params={"name": "rancher-spike"},
    )
    stubber.add_response(
        "create_api_key_credential_provider",
        provider_response(),
        {"name": "rancher-spike", "apiKey": TOKEN, "tags": ANY},
    )
    stubber.add_response("list_gateways", {"items": []}, {})
    stubber.add_response(
        "create_gateway",
        gateway("CREATING"),
        {
            "name": "rancher-spike",
            "description": ANY,
            "roleArn": ANY,
            "protocolType": "MCP",
            "authorizerType": "AWS_IAM",
            "tags": ANY,
        },
    )
    stubber.add_response("get_gateway", gateway("CREATING"), {"gatewayIdentifier": GW_ID})
    stubber.add_response("get_gateway", gateway("READY"), {"gatewayIdentifier": GW_ID})
    stubber.add_response("list_gateway_targets", {"items": []}, {"gatewayIdentifier": GW_ID})

    def capture(name):
        expect["target_request"] = name
        return True

    stubber.add_response(
        "create_gateway_target",
        target("CREATING"),
        {
            "gatewayIdentifier": GW_ID,
            "name": "rancher",
            "description": ANY,
            "targetConfiguration": {
                "mcp": {"mcpServer": {"endpoint": f"https://mcp-spike.{DOMAIN}/mcp"}}
            },
            "credentialProviderConfigurations": [
                {
                    "credentialProviderType": "API_KEY",
                    "credentialProvider": {
                        "apiKeyCredentialProvider": {
                            "providerArn": PROVIDER_ARN,
                            "credentialParameterName": "R_token",
                            "credentialLocation": "HEADER",
                        }
                    },
                }
            ],
            "privateEndpoint": ANY,
        },
    )
    stubber.add_response(
        "get_gateway_target",
        target("CREATING"),
        {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )
    stubber.add_response(
        "get_gateway_target",
        target("READY"),
        {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
    )


def test_apply_builds_everything_once_and_prints_no_private_value(aws):
    expect = {}
    clients, seams, out, stream, stubber, remote = make(aws, lambda s: fresh_agentcore(s, expect))

    assert sg.run(clients, seams, out, apply=True) == 0, stream.getvalue()
    stubber.assert_no_pending_responses()

    printed = stream.getvalue()
    for private in (DOMAIN, TOKEN, "123456789012"):
        assert private not in printed
    assert "A5 is set up" in printed.splitlines()[-1]
    assert len(remote) == 1
    assert "serve --insecure --read-only --port 9092" in remote[0][1]

    ec2 = aws.client("ec2")
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]
    groups = {g["GroupName"]: g for g in ec2.describe_security_groups()["SecurityGroups"]}
    alb_rules = groups["mcp-spike-alb"]["IpPermissions"]
    assert [(r["FromPort"], [i["CidrIp"] for i in r["IpRanges"]]) for r in alb_rules] == [
        (443, [vpc["CidrBlock"]])
    ]
    instance_rules = groups["rancher-spike"]["IpPermissions"]
    assert any(
        r["FromPort"] == 9092
        and [p["GroupId"] for p in r["UserIdGroupPairs"]] == [groups["mcp-spike-alb"]["GroupId"]]
        for r in instance_rules
    )
    assert not any(r.get("IpRanges") and r["FromPort"] == 9092 for r in instance_rules)
    assert "mcp-spike-gateway" in groups

    elb = aws.client("elbv2")
    lb = elb.describe_load_balancers(Names=["mcp-spike"])["LoadBalancers"][0]
    assert lb["Scheme"] == "internal"
    assert len(lb["AvailabilityZones"]) == 2
    instance_subnet = aws.client("ec2").describe_instances()["Reservations"][0]["Instances"][0][
        "SubnetId"
    ]
    assert instance_subnet in [z["SubnetId"] for z in lb["AvailabilityZones"]]
    attrs = {
        a["Key"]: a["Value"]
        for a in elb.describe_load_balancer_attributes(LoadBalancerArn=lb["LoadBalancerArn"])[
            "Attributes"
        ]
    }
    assert attrs["routing.http.drop_invalid_header_fields.enabled"] == "false"
    tg = elb.describe_target_groups(Names=["mcp-spike"])["TargetGroups"][0]
    assert (tg["Protocol"], tg["Port"], tg["Matcher"]["HttpCode"]) == ("HTTP", 9092, "200-499")
    (listener,) = elb.describe_listeners(LoadBalancerArn=lb["LoadBalancerArn"])["Listeners"]
    assert (listener["Protocol"], listener["Port"]) == ("HTTPS", 443)
    assert listener["DefaultActions"][0]["TargetGroupArn"] == tg["TargetGroupArn"]

    cert = aws.client("acm").list_certificates()["CertificateSummaryList"]
    assert [c["DomainName"] for c in cert] == [f"mcp-spike.{DOMAIN}"]

    iam = aws.client("iam")
    role = iam.get_role(RoleName="rancher-spike-gateway")["Role"]
    trust = role["AssumeRolePolicyDocument"]
    statement = trust["Statement"][0]
    assert statement["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert statement["Condition"]["ArnLike"]["aws:SourceArn"].endswith(":gateway/rancher-spike-*")
    policy = iam.get_role_policy(
        RoleName="rancher-spike-gateway", PolicyName="gateway-reads-the-rancher-token"
    )["PolicyDocument"]
    by_sid = {s["Sid"]: s for s in policy["Statement"]}
    assert by_sid["RancherTokenSecret"]["Resource"] == SECRET_ARN
    assert PROVIDER_ARN in by_sid["RancherTokenFromTheVault"]["Resource"]
    assert any(
        r.endswith(":workload-identity-directory/default/workload-identity/rancher-spike-*")
        for r in by_sid["RancherTokenFromTheVault"]["Resource"]
    )
    assert all(
        r != "*"
        for s in policy["Statement"]
        for r in ([s["Resource"]] if isinstance(s["Resource"], str) else s["Resource"])
    )

    state = json.loads((sg.STATE_DIR / "gateway.json").read_text())
    assert state["gatewayId"] == GW_ID
    assert state["targetId"] == "TARGET1234"
    assert oct((sg.STATE_DIR / "gateway.json").stat().st_mode)[-3:] == "600"


def test_the_target_request_routes_privately_to_the_internal_alb(aws):
    clients, _seams, out, _stream, _stubber, _remote = make(aws, lambda s: None)
    ctx = sg.discover(clients, out)
    request = sg.target_request(
        ctx,
        PROVIDER_ARN,
        "sg-0123456789abcdef0",
        "internal-mcp-spike-1.us-east-1.elb.amazonaws.com",
    )
    managed = request["privateEndpoint"]["managedVpcResource"]
    assert managed["routingDomain"].startswith("internal-")
    assert managed["endpointIpAddressType"] == "IPV4"
    assert set(ctx.endpoint_az_ids) <= set(sg.ALLOWED_AZ_IDS)
    assert len(set(ctx.endpoint_az_ids)) == 2
    assert managed["subnetIds"] == ctx.endpoint_subnet_ids
    # The instance sits in use1-az3: the ALB must include that zone; Lattice must not get it.
    assert ctx.instance_az_id == "use1-az3"
    assert ctx.alb_az_ids[0] == "use1-az3"
    assert len(set(ctx.alb_az_ids)) == 2
    assert "use1-az3" not in ctx.endpoint_az_ids
    # The request validates against the real model.
    agentcore = aws.client("bedrock-agentcore-control")
    stub = Stubber(agentcore)
    stub.add_response(
        "create_gateway_target", target("CREATING"), {"gatewayIdentifier": GW_ID, **request}
    )
    with stub:
        agentcore.create_gateway_target(gatewayIdentifier=GW_ID, **request)


def test_second_apply_creates_nothing_new(aws):
    expect = {}
    clients, seams, out, stream, _stubber, _remote = make(aws, lambda s: fresh_agentcore(s, expect))
    assert sg.run(clients, seams, out, apply=True) == 0, stream.getvalue()

    def again(stubber):
        stubber.add_response(
            "get_api_key_credential_provider",
            {**provider_response(), "createdTime": NOW, "lastUpdatedTime": NOW},
            {"name": "rancher-spike"},
        )
        stubber.add_response(
            "update_api_key_credential_provider",
            {**provider_response(), "createdTime": NOW, "lastUpdatedTime": NOW},
            {"name": "rancher-spike", "apiKey": TOKEN},
        )
        stubber.add_response(
            "list_gateways",
            {
                "items": [
                    {
                        "gatewayId": GW_ID,
                        "name": "rancher-spike",
                        "status": "READY",
                        "createdAt": NOW,
                        "updatedAt": NOW,
                        "authorizerType": "AWS_IAM",
                    }
                ]
            },
            {},
        )
        stubber.add_response("get_gateway", gateway("READY"), {"gatewayIdentifier": GW_ID})
        stubber.add_response(
            "list_gateway_targets",
            {
                "items": [
                    {
                        "targetId": "TARGET1234",
                        "name": "rancher",
                        "status": "READY",
                        "createdAt": NOW,
                        "updatedAt": NOW,
                    }
                ]
            },
            {"gatewayIdentifier": GW_ID},
        )
        stubber.add_response(
            "get_gateway_target",
            target("READY"),
            {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"},
        )

    clients2, seams2, out2, stream2, stubber2, _remote2 = make(aws, again)
    assert sg.run(clients2, seams2, out2, apply=True) == 0, stream2.getvalue()
    stubber2.assert_no_pending_responses()
    elb = aws.client("elbv2")
    assert len(elb.describe_load_balancers()["LoadBalancers"]) == 1
    assert len(elb.describe_target_groups()["TargetGroups"]) == 1
    assert len(aws.client("acm").list_certificates()["CertificateSummaryList"]) == 1
    names = [g["GroupName"] for g in aws.client("ec2").describe_security_groups()["SecurityGroups"]]
    assert names.count("mcp-spike-alb") == 1
    assert names.count("mcp-spike-gateway") == 1
    assert "created" not in stream2.getvalue().replace("key refreshed", "")
    assert "now also in the instance's zone" not in stream2.getvalue()


def test_plan_reads_only_and_counts_what_is_missing(aws):
    def reads(stubber):
        stubber.add_client_error(
            "get_api_key_credential_provider",
            service_error_code="ResourceNotFoundException",
            http_status_code=404,
        )
        stubber.add_response("list_gateways", {"items": []}, {})

    clients, seams, out, stream, stubber, remote = make(aws, reads)
    assert sg.run(clients, seams, out, apply=False) == 0, stream.getvalue()
    stubber.assert_no_pending_responses()
    assert remote == []
    printed = stream.getvalue()
    assert printed.splitlines()[-1].startswith("Plan: ")
    assert DOMAIN not in printed
    assert "123456789012" not in printed
    names = [g["GroupName"] for g in aws.client("ec2").describe_security_groups()["SecurityGroups"]]
    assert "mcp-spike-alb" not in names
    assert aws.client("elbv2").describe_load_balancers()["LoadBalancers"] == []
    assert aws.client("acm").list_certificates()["CertificateSummaryList"] == []


def test_plan_with_read_only_credentials_that_cannot_read_agentcore(aws):
    def denied(stubber):
        stubber.add_client_error(
            "get_api_key_credential_provider",
            service_error_code="AccessDeniedException",
            http_status_code=403,
        )

    clients, seams, out, stream, _stubber, _remote = make(aws, denied)
    assert sg.run(clients, seams, out, apply=False) == 0, stream.getvalue()
    assert "these credentials cannot read AgentCore" in stream.getvalue()


def test_a_failed_target_is_reported_with_its_reasons(aws):
    def failing(stubber):
        stubber.add_client_error(
            "get_api_key_credential_provider",
            service_error_code="ResourceNotFoundException",
            http_status_code=404,
        )
        stubber.add_response(
            "create_api_key_credential_provider",
            provider_response(),
            {"name": "rancher-spike", "apiKey": TOKEN, "tags": ANY},
        )
        stubber.add_response("list_gateways", {"items": []}, {})
        stubber.add_response("create_gateway", gateway("READY"), None)
        stubber.add_response("get_gateway", gateway("READY"), {"gatewayIdentifier": GW_ID})
        stubber.add_response("list_gateway_targets", {"items": []}, {"gatewayIdentifier": GW_ID})
        stubber.add_response("create_gateway_target", target("CREATING"), None)
        failed = {
            **target("FAILED"),
            "statusReasons": [
                f"Unable to connect to https://mcp-spike.{DOMAIN}/mcp from account 123456789012"
            ],
        }
        stubber.add_response(
            "get_gateway_target", failed, {"gatewayIdentifier": GW_ID, "targetId": "TARGET1234"}
        )

    clients, seams, out, _stream, _stubber, _remote = make(aws, failing)
    with pytest.raises(sg.SetupError) as raised:
        sg.run(clients, seams, out, apply=True)
    message = out.redact(str(raised.value))
    assert (
        message == "the target is FAILED: Unable to connect to https://mcp-spike.<domain>/mcp"
        " from account <account>"
    )


def test_missing_token_stops_before_anything_in_agentcore(aws):
    def provider_only(stubber):
        stubber.add_client_error(
            "get_api_key_credential_provider",
            service_error_code="ResourceNotFoundException",
            http_status_code=404,
        )

    clients, seams, out, _stream, _stubber, _remote = make(aws, provider_only)
    seams = sg.Seams(
        keychain_token=lambda: None,
        run_on_instance=seams.run_on_instance,
        sleep=seams.sleep,
        monotonic=seams.monotonic,
    )
    with pytest.raises(sg.SetupError, match="no sre-agent-token in the Keychain"):
        sg.run(clients, seams, out, apply=True)


def test_the_instance_script_has_no_secret_and_reads_only_tools():
    script = sg.REMOTE_SETUP
    assert "--read-only" in script
    assert "--insecure" in script
    assert "token" not in script.lower()
    assert "46f49c7e4e296e003b01c05ab97fb918c733cb49" in script
    assert "{{.State.Running}}" in script
    assert "%{http_code}" in script


def test_two_zones_puts_the_first_zone_first_and_respects_only():
    subnets = [
        {"SubnetId": f"subnet-{z}", "AvailabilityZoneId": z}
        for z in ("use1-az3", "use1-az6", "use1-az1", "use1-az2")
    ]
    assert [s["AvailabilityZoneId"] for s in sg.two_zones(subnets, "use1-az6")] == [
        "use1-az6",
        "use1-az1",
    ]
    assert [s["AvailabilityZoneId"] for s in sg.two_zones(subnets, "use1-az3")] == [
        "use1-az3",
        "use1-az1",
    ]
    assert [
        s["AvailabilityZoneId"] for s in sg.two_zones(subnets, "use1-az3", only=sg.ALLOWED_AZ_IDS)
    ] == ["use1-az1", "use1-az2"]
    assert sg.two_zones([], "use1-az1") == []


def test_every_ec2_description_uses_only_the_characters_ec2_accepts():
    import re

    texts = [
        sg.ALB_SECURITY_GROUP_DESCRIPTION,
        sg.GATEWAY_SECURITY_GROUP_DESCRIPTION,
        "HTTPS from the VPC",
        "rancher-ai-mcp from the internal ALB",
    ]
    for text in texts:
        assert re.fullmatch(sg.EC2_DESCRIPTION, text), text
    assert not re.fullmatch(sg.EC2_DESCRIPTION, "Gateway's")
    source = (REPO / "tools/spikes/spike-a/setup_gateway.py").read_text()
    # Every literal handed to an EC2 rule description is one of the texts above.
    for found in re.findall(r'allow_ingress\(\s*clients,\s*[^,]+,\s*[^,]+,\s*"([^"]+)"', source):
        assert re.fullmatch(sg.EC2_DESCRIPTION, found), found


def test_debug_on_and_off_update_the_gateway_and_keep_its_settings(aws):
    current = {
        **gateway("READY"),
        "roleArn": "arn:aws:iam::123456789012:role/rancher-spike-gateway",
        "description": "d",
        "protocolType": "MCP",
    }

    def stubs(stubber):
        stubber.add_response(
            "list_gateways",
            {
                "items": [
                    {
                        "gatewayId": GW_ID,
                        "name": "rancher-spike",
                        "status": "READY",
                        "createdAt": NOW,
                        "updatedAt": NOW,
                        "authorizerType": "AWS_IAM",
                    }
                ]
            },
            {},
        )
        stubber.add_response("get_gateway", current, {"gatewayIdentifier": GW_ID})
        stubber.add_response(
            "update_gateway",
            current,
            {
                "gatewayIdentifier": GW_ID,
                "name": "rancher-spike",
                "roleArn": current["roleArn"],
                "protocolType": "MCP",
                "authorizerType": "AWS_IAM",
                "description": "d",
                "exceptionLevel": "DEBUG",
            },
        )
        stubber.add_response(
            "get_gateway", {**current, "status": "UPDATING"}, {"gatewayIdentifier": GW_ID}
        )
        stubber.add_response("get_gateway", current, {"gatewayIdentifier": GW_ID})
        stubber.add_response(
            "list_gateways",
            {
                "items": [
                    {
                        "gatewayId": GW_ID,
                        "name": "rancher-spike",
                        "status": "READY",
                        "createdAt": NOW,
                        "updatedAt": NOW,
                        "authorizerType": "AWS_IAM",
                    }
                ]
            },
            {},
        )
        stubber.add_response("get_gateway", current, {"gatewayIdentifier": GW_ID})
        stubber.add_response(
            "update_gateway",
            current,
            {
                "gatewayIdentifier": GW_ID,
                "name": "rancher-spike",
                "roleArn": current["roleArn"],
                "protocolType": "MCP",
                "authorizerType": "AWS_IAM",
                "description": "d",
            },
        )
        stubber.add_response("get_gateway", current, {"gatewayIdentifier": GW_ID})

    clients, seams, out, stream, stubber, _remote = make(aws, stubs)
    assert sg.set_debug(clients, seams, out, on=True) == 0
    assert sg.set_debug(clients, seams, out, on=False) == 0
    stubber.assert_no_pending_responses()
    assert "detailed errors on" in stream.getvalue()
    assert "detailed errors off" in stream.getvalue()


def test_the_probe_scrubs_tokens_hostnames_and_accounts():
    spec2 = importlib.util.spec_from_file_location(
        "mcp_probe", REPO / "tools/spikes/spike-a/mcp_probe.py"
    )
    probe = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(probe)
    text = (
        "failed https://mcp-spike.example.co.uk/mcp for 123456789012 with token-abcde:SECRETvalue1"
    )
    assert (
        probe.scrub(text)
        == "failed https://mcp-spike.<domain>/mcp for <account> with token-[redacted]"
    )


def test_an_existing_alb_without_the_instance_zone_gets_it(aws):
    ec2 = aws.client("ec2")
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]
    subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}])[
        "Subnets"
    ]
    elsewhere = [
        s["SubnetId"] for s in subnets if s["AvailabilityZoneId"] in ("use1-az1", "use1-az2")
    ]
    elb = aws.client("elbv2")
    elb.create_load_balancer(
        Name="mcp-spike", Subnets=elsewhere, Scheme="internal", Type="application"
    )
    expect = {}
    clients, seams, out, stream, _stubber, _remote = make(aws, lambda s: fresh_agentcore(s, expect))

    assert sg.run(clients, seams, out, apply=True) == 0, stream.getvalue()

    assert "now also in the instance's zone" in stream.getvalue()
    instance_subnet = ec2.describe_instances()["Reservations"][0]["Instances"][0]["SubnetId"]
    balancer = elb.describe_load_balancers(Names=["mcp-spike"])["LoadBalancers"][0]
    assert instance_subnet in [z["SubnetId"] for z in balancer["AvailabilityZones"]]
