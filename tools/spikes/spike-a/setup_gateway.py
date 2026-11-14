#!/usr/bin/env python3
"""Spike A, A5: reach rancher-ai-mcp through AgentCore Gateway over a private VPC Lattice endpoint.

Run from the repository root:

    uv run python tools/spikes/spike-a/setup_gateway.py plan    # read-only: what is missing
    uv run python tools/spikes/spike-a/setup_gateway.py apply   # admin terminal: create it

The design under test (input to ADR-0002):

- rancher-ai-mcp runs on the rancher-spike instance in HTTP mode, with only its read tools,
  on port 9092 (plain HTTP inside the VPC), and calls Rancher on the same host. Outside a
  cluster its HTTP mode needs --insecure, which also skips Rancher's certificate check there.
- An internal ALB, mcp-spike, terminates TLS with a public ACM certificate for
  mcp-spike.<domain> and forwards to that port; only the ALB's security group may reach it.
  The ALB keeps routing.http.drop_invalid_header_fields off, because the token header name,
  R_token, has an underscore that the ALB would otherwise drop.
- AgentCore Gateway rancher-spike (AWS_IAM inbound) has one MCP target, rancher, at
  https://mcp-spike.<domain>/mcp. A managed VPC Lattice private endpoint in the default VPC
  routes it to the internal ALB (routingDomain), so nothing is open to the internet. The
  certificate is publicly issued and matches the URL host, so the gateway trusts it as is.
- The gateway sends sre-agent's Rancher token in the R_token header, from the API key
  credential provider rancher-spike, kept in Secrets Manager. The token comes from your
  Keychain (service rancher-spike, account sre-agent-token) and is never printed.

Each step finds what an earlier run created and creates only what is missing. The script
prints no secret, no account ID and no domain (shown as <domain>). It ends by writing
~/.rancher-spike/gateway.json, which mcp_probe.py --gateway and the teardown read.

Exit status: 0 on success, 1 when a step fails (fix the cause and run it again), 2 on a
usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

import boto3
from botocore.exceptions import BotoCoreError, ClientError

REGION = "us-east-1"
DOMAIN_PARAMETER = "/sre-lab/domain-name"
HOST_LABEL = "mcp-spike"
INSTANCE_NAME = "rancher-spike"
ALB_NAME = "mcp-spike"
TARGET_GROUP_NAME = "mcp-spike"
ALB_SECURITY_GROUP = "mcp-spike-alb"
GATEWAY_SECURITY_GROUP = "mcp-spike-gateway"
# EC2 accepts only a-zA-Z0-9, space and ._-:/()#,@[]+=&;{}!$* in these: no apostrophe.
ALB_SECURITY_GROUP_DESCRIPTION = (
    "Spike A, A5: internal ALB for rancher-ai-mcp; HTTPS from the VPC only"
)
GATEWAY_SECURITY_GROUP_DESCRIPTION = (
    "Spike A, A5: AgentCore Gateway managed VPC Lattice resource gateway"
)
EC2_DESCRIPTION = r"[a-zA-Z0-9. _\-:/()#,@\[\]+=&;{}!$*]{0,255}"
PROVIDER_NAME = "rancher-spike"
ROLE_NAME = "rancher-spike-gateway"
ROLE_POLICY_NAME = "gateway-reads-the-rancher-token"
GATEWAY_NAME = "rancher-spike"
TARGET_NAME = "rancher"
MCP_PORT = 9092
TOKEN_HEADER = "R_token"  # noqa: S105 - a header name
KEYCHAIN_SERVICE = "rancher-spike"
KEYCHAIN_TOKEN_ACCOUNT = "sre-agent-token"  # noqa: S105 - a Keychain account name
# Lattice managed endpoints in us-east-1 accept subnets in these Availability Zone IDs only.
ALLOWED_AZ_IDS = ("use1-az1", "use1-az2", "use1-az4", "use1-az5", "use1-az6")
SSL_POLICY = "ELBSecurityPolicy-TLS13-1-2-2021-06"
IMAGE = "rancher-ai-mcp:v1.2.0-alpha.5"
SOURCE_COMMIT = "46f49c7e4e296e003b01c05ab97fb918c733cb49"
STATE_DIR = Path.home() / ".rancher-spike"
SPIKE_TAG = ("spike", "a5")
SECURITY = "/usr/bin/security"
SSH = "/usr/bin/ssh"
BROKEN_TARGET_STATES = ("FAILED", "UPDATE_UNSUCCESSFUL", "SYNCHRONIZE_UNSUCCESSFUL")

# Runs on the instance from a file, with stdin from /dev/null, so no command can wait for input
# or read the script itself. Lines starting "progress:" are relayed to you as they come.
REMOTE_SETUP = f"""set -euo pipefail
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a
image={IMAGE}
say() {{ echo "progress: $*"; }}
if ! sudo docker image inspect "$image" >/dev/null 2>&1; then
  if ! sudo docker buildx version >/dev/null 2>&1; then
    say "installing docker-buildx and git"
    sudo -E dpkg --configure -a
    sudo -E apt-get -o DPkg::Lock::Timeout=600 -qq update
    sudo -E apt-get -o DPkg::Lock::Timeout=600 -qq install -y docker-buildx git >/dev/null
  fi
  say "building rancher-ai-mcp for x86, the slow part: 5 to 15 minutes on this instance"
  start=$(date +%s)
  ( while sleep 60; do say "still building, $(( ($(date +%s) - start) / 60 )) min so far"; done ) &
  beat=$!
  # shellcheck disable=SC2024  # the log is the ubuntu user's file in /tmp, on purpose
  if ! sudo docker buildx build --progress=plain --load -t "$image" \\
      --build-arg VERSION=v1.2.0-alpha.5 --build-arg COMMIT={SOURCE_COMMIT} \\
      -f package/Dockerfile 'https://github.com/rancher/rancher-ai-mcp.git#{SOURCE_COMMIT}' \\
      >/tmp/rancher-mcp-build.log 2>&1; then
    kill "$beat" 2>/dev/null || true
    say "the build failed; the last lines of /tmp/rancher-mcp-build.log follow"
    tail -n 15 /tmp/rancher-mcp-build.log
    exit 1
  fi
  kill "$beat" 2>/dev/null || true
  say "built in $(( ($(date +%s) - start) / 60 )) min"
fi
running=$(sudo docker inspect -f '{{{{.State.Running}}}}' rancher-mcp 2>/dev/null || true)
if [ "$running" != "true" ]; then
  say "starting rancher-ai-mcp, read tools only, on port {MCP_PORT}"
  sudo docker rm -f rancher-mcp >/dev/null 2>&1 || true
  sudo docker run -d --name rancher-mcp --restart unless-stopped --network host \\
    -e RANCHER_URL=https://127.0.0.1 "$image" \\
    /usr/local/bin/mcp serve --insecure --read-only --port {MCP_PORT} >/dev/null
fi
code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{MCP_PORT}/ || true)
  [ "$code" != "000" ] && break
  sleep 2
done
echo "mcp-http-status=$code"
"""


class SetupError(Exception):
    """A step failed. The message is printed only after redaction."""


@dataclass
class Out:
    """Prints progress with the domain, the account ID and every secret hidden."""

    stream: TextIO = field(default_factory=lambda: sys.stdout)
    replacements: dict[str, str] = field(default_factory=dict)

    def hide(self, value: str, label: str) -> None:
        if value:
            self.replacements[value] = label

    def redact(self, text: str) -> str:
        for value in sorted(self.replacements, key=len, reverse=True):
            text = text.replace(value, self.replacements[value])
        return re.sub(r"\b\d{12}\b", "<account>", text)

    def say(self, text: str) -> None:
        print(self.redact(text), file=self.stream, flush=True)


@dataclass(frozen=True)
class Clients:
    ec2: Any
    elbv2: Any
    acm: Any
    route53: Any
    iam: Any
    ssm: Any
    sts: Any
    agentcore: Any

    @classmethod
    def from_session(cls, session: boto3.Session) -> Clients:
        return cls(
            ec2=session.client("ec2"),
            elbv2=session.client("elbv2"),
            acm=session.client("acm"),
            route53=session.client("route53"),
            iam=session.client("iam"),
            ssm=session.client("ssm"),
            sts=session.client("sts"),
            agentcore=session.client("bedrock-agentcore-control"),
        )


@dataclass(frozen=True)
class Seams:
    """What the script reaches outside AWS's APIs; tests replace each one."""

    keychain_token: Callable[[], str | None]
    run_on_instance: Callable[[str, str], str]
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


@dataclass
class Context:
    account: str
    domain: str
    zone_id: str
    vpc_id: str
    vpc_cidr: str
    alb_subnet_ids: list[str]
    alb_az_ids: list[str]
    endpoint_subnet_ids: list[str]
    endpoint_az_ids: list[str]
    instance_id: str
    instance_az_id: str
    instance_public_ip: str
    instance_security_group: str

    @property
    def fqdn(self) -> str:
        return f"{HOST_LABEL}.{self.domain}"

    @property
    def endpoint(self) -> str:
        return f"https://{self.fqdn}/mcp"


@dataclass
class Plan:
    """Counts what is in place and what a plan run would create or change."""

    in_place: int = 0
    to_change: list[str] = field(default_factory=list)

    def have(self) -> None:
        self.in_place += 1

    def need(self, what: str) -> None:
        self.to_change.append(what)


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _tags(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"Key": key, "Value": value} for key, value in pairs]


def two_zones(
    subnets: list[dict[str, Any]], first: str, only: Sequence[str] | None = None
) -> list[dict[str, Any]]:
    """Pick subnets in up to two Availability Zones, the zone ID `first` before any other.

    With `only`, keep to those zone IDs. Otherwise prefer the zones Lattice accepts, so the
    load balancer and the private endpoint share a zone when they can.
    """
    pool = [s for s in subnets if only is None or s.get("AvailabilityZoneId") in only]
    pool.sort(
        key=lambda s: (
            s.get("AvailabilityZoneId") != first,
            s.get("AvailabilityZoneId") not in ALLOWED_AZ_IDS,
            str(s.get("AvailabilityZoneId")),
        )
    )
    chosen: list[dict[str, Any]] = []
    for subnet in pool:
        if subnet["AvailabilityZoneId"] not in [c["AvailabilityZoneId"] for c in chosen]:
            chosen.append(subnet)
        if len(chosen) == 2:
            break
    return chosen


# Discovery -----------------------------------------------------------------------


def discover(clients: Clients, out: Out) -> Context:
    """Read everything the steps need. Read-only."""
    account = clients.sts.get_caller_identity()["Account"]
    try:
        domain = clients.ssm.get_parameter(Name=DOMAIN_PARAMETER)["Parameter"]["Value"]
    except ClientError as error:
        raise SetupError(f"cannot read {DOMAIN_PARAMETER} ({_code(error)})") from error
    out.hide(domain, "<domain>")
    zones = clients.route53.list_hosted_zones_by_name(DNSName=domain)["HostedZones"]
    public = [
        z
        for z in zones
        if z["Name"].rstrip(".") == domain and not z.get("Config", {}).get("PrivateZone")
    ]
    if not public:
        raise SetupError("no public Route 53 zone for <domain>")
    zone_id = public[0]["Id"].split("/")[-1]

    vpcs = clients.ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    if not vpcs:
        raise SetupError("no default VPC in us-east-1 (A1 creates it)")
    vpc = vpcs[0]
    subnets = clients.ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}])[
        "Subnets"
    ]

    reservations = clients.ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [INSTANCE_NAME]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )["Reservations"]
    instances = [i for r in reservations for i in r["Instances"]]
    if len(instances) != 1:
        raise SetupError(f"expected one running {INSTANCE_NAME} instance, found {len(instances)}")
    instance = instances[0]
    groups = [g["GroupId"] for g in instance["SecurityGroups"] if g["GroupName"] == INSTANCE_NAME]
    if not groups:
        raise SetupError(f"the instance has no {INSTANCE_NAME} security group")
    out.hide(str(instance.get("PublicIpAddress", "")), "<instance-ip>")
    own = [s for s in subnets if s["SubnetId"] == instance.get("SubnetId")]
    if not own:
        raise SetupError("the instance is not in the default VPC")
    instance_az = str(own[0]["AvailabilityZoneId"])
    # An ALB routes only to targets in the zones it has, so the instance's zone comes first.
    alb = two_zones(subnets, instance_az)
    if len(alb) < 2 or alb[0]["AvailabilityZoneId"] != instance_az:
        raise SetupError("the default VPC needs a second zone for the load balancer")
    # Lattice's managed endpoint takes subnets only in ALLOWED_AZ_IDS.
    endpoint = two_zones(subnets, instance_az, only=ALLOWED_AZ_IDS)
    if not endpoint:
        raise SetupError("the default VPC has no subnet in " + ", ".join(ALLOWED_AZ_IDS))
    context = Context(
        account=account,
        domain=domain,
        zone_id=zone_id,
        vpc_id=vpc["VpcId"],
        vpc_cidr=vpc["CidrBlock"],
        alb_subnet_ids=[s["SubnetId"] for s in alb],
        alb_az_ids=[s["AvailabilityZoneId"] for s in alb],
        endpoint_subnet_ids=[s["SubnetId"] for s in endpoint],
        endpoint_az_ids=[s["AvailabilityZoneId"] for s in endpoint],
        instance_id=instance["InstanceId"],
        instance_az_id=instance_az,
        instance_public_ip=str(instance.get("PublicIpAddress", "")),
        instance_security_group=groups[0],
    )
    out.say(
        f"Found: default VPC {context.vpc_cidr}; instance {context.instance_id} in "
        f"{context.instance_az_id}; load balancer zones {', '.join(context.alb_az_ids)}; "
        f"private endpoint zones {', '.join(context.endpoint_az_ids)}; public zone for <domain>."
    )
    return context


# Steps ---------------------------------------------------------------------------


def ensure_mcp_server(ctx: Context, seams: Seams, out: Out, plan: Plan, apply: bool) -> None:
    """Build and run rancher-ai-mcp on the instance (over SSH); report its HTTP status."""
    if not apply:
        plan.need("rancher-ai-mcp on the instance (checked and started over SSH by apply)")
        out.say("Server: apply builds rancher-ai-mcp for x86 on the instance and runs it.")
        return
    out.say("Server: checking rancher-ai-mcp on the instance; a first build prints progress ...")
    report = seams.run_on_instance(ctx.instance_public_ip, REMOTE_SETUP)
    match = re.search(r"mcp-http-status=(\d{3})", report)
    if not match or match.group(1) == "000":
        raise SetupError("rancher-ai-mcp did not answer on the instance's port 9092")
    out.say(f"Server: rancher-ai-mcp answers on port {MCP_PORT} (HTTP {match.group(1)}).")


def find_certificate(clients: Clients, fqdn: str) -> str | None:
    paginator = clients.acm.get_paginator("list_certificates")
    for page in paginator.paginate(CertificateStatuses=["PENDING_VALIDATION", "ISSUED"]):
        for summary in page["CertificateSummaryList"]:
            if summary.get("DomainName") == fqdn:
                return str(summary["CertificateArn"])
    return None


def ensure_certificate(
    clients: Clients, ctx: Context, seams: Seams, out: Out, plan: Plan, apply: bool
) -> str | None:
    """Request the ACM certificate and put its validation record in the public zone."""
    arn = find_certificate(clients, ctx.fqdn)
    if arn is None and not apply:
        plan.need("ACM certificate for mcp-spike.<domain>")
        out.say("Certificate: to request for mcp-spike.<domain>, validated by DNS.")
        return None
    if arn is None:
        arn = clients.acm.request_certificate(
            DomainName=ctx.fqdn,
            ValidationMethod="DNS",
            Tags=_tags(("Name", HOST_LABEL), SPIKE_TAG),
        )["CertificateArn"]
        out.say("Certificate: requested.")
    else:
        plan.have()
    certificate = clients.acm.describe_certificate(CertificateArn=arn)["Certificate"]
    if certificate["Status"] == "ISSUED":
        out.say("Certificate: issued.")
        return arn
    if not apply:
        out.say(f"Certificate: {certificate['Status']}.")
        return arn
    deadline = seams.monotonic() + 120
    record = None
    while record is None:
        options = certificate.get("DomainValidationOptions") or [{}]
        record = options[0].get("ResourceRecord")
        if record is None:
            if seams.monotonic() >= deadline:
                raise SetupError("ACM gave no DNS validation record within 2 minutes")
            seams.sleep(5)
            certificate = clients.acm.describe_certificate(CertificateArn=arn)["Certificate"]
    clients.route53.change_resource_record_sets(
        HostedZoneId=ctx.zone_id,
        ChangeBatch={
            "Comment": "Spike A, A5: ACM validation for mcp-spike",
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
            ],
        },
    )
    out.say("Certificate: validation record in place.")
    return arn


def wait_certificate(clients: Clients, arn: str, out: Out) -> None:
    out.say("Certificate: waiting for ACM to issue it (usually 2 to 5 minutes) ...")
    try:
        clients.acm.get_waiter("certificate_validated").wait(
            CertificateArn=arn, WaiterConfig={"Delay": 15, "MaxAttempts": 60}
        )
    except Exception as error:  # botocore WaiterError
        raise SetupError(f"the certificate was not issued: {error}") from error
    out.say("Certificate: issued.")


def ensure_security_group(
    clients: Clients, ctx: Context, name: str, description: str, out: Out, plan: Plan, apply: bool
) -> str | None:
    found = clients.ec2.describe_security_groups(
        Filters=[
            {"Name": "vpc-id", "Values": [ctx.vpc_id]},
            {"Name": "group-name", "Values": [name]},
        ]
    )["SecurityGroups"]
    if found:
        plan.have()
        return str(found[0]["GroupId"])
    if not apply:
        plan.need(f"security group {name}")
        out.say(f"Security group {name}: to create.")
        return None
    group_id = clients.ec2.create_security_group(
        GroupName=name,
        Description=description,
        VpcId=ctx.vpc_id,
        TagSpecifications=[
            {"ResourceType": "security-group", "Tags": _tags(("Name", name), SPIKE_TAG)}
        ],
    )["GroupId"]
    out.say(f"Security group {name}: created.")
    return str(group_id)


def allow_ingress(
    clients: Clients,
    group_id: str,
    port: int,
    description: str,
    *,
    cidr: str | None = None,
    source_group: str | None = None,
) -> bool:
    """Add one inbound TCP rule; return False when it was already there."""
    permission: dict[str, Any] = {"IpProtocol": "tcp", "FromPort": port, "ToPort": port}
    if cidr:
        permission["IpRanges"] = [{"CidrIp": cidr, "Description": description}]
    else:
        permission["UserIdGroupPairs"] = [{"GroupId": source_group, "Description": description}]
    try:
        clients.ec2.authorize_security_group_ingress(GroupId=group_id, IpPermissions=[permission])
    except ClientError as error:
        if _code(error) == "InvalidPermission.Duplicate":
            return False
        raise
    return True


def has_ingress(clients: Clients, group_id: str, port: int, source_group: str) -> bool:
    group = clients.ec2.describe_security_groups(GroupIds=[group_id])["SecurityGroups"][0]
    return any(
        p.get("FromPort") == port
        and any(pair.get("GroupId") == source_group for pair in p.get("UserIdGroupPairs", []))
        for p in group.get("IpPermissions", [])
    )


def ensure_network(
    clients: Clients, ctx: Context, out: Out, plan: Plan, apply: bool
) -> tuple[str | None, str | None]:
    alb_group = ensure_security_group(
        clients,
        ctx,
        ALB_SECURITY_GROUP,
        ALB_SECURITY_GROUP_DESCRIPTION,
        out,
        plan,
        apply,
    )
    gateway_group = ensure_security_group(
        clients,
        ctx,
        GATEWAY_SECURITY_GROUP,
        GATEWAY_SECURITY_GROUP_DESCRIPTION,
        out,
        plan,
        apply,
    )
    if (
        alb_group
        and apply
        and allow_ingress(clients, alb_group, 443, "HTTPS from the VPC", cidr=ctx.vpc_cidr)
    ):
        out.say(f"Security group {ALB_SECURITY_GROUP}: HTTPS allowed from the VPC.")
    if alb_group and has_ingress(clients, ctx.instance_security_group, MCP_PORT, alb_group):
        plan.have()
    elif not apply:
        plan.need(f"port {MCP_PORT} on {INSTANCE_NAME} from {ALB_SECURITY_GROUP}")
        out.say(f"Security group {INSTANCE_NAME}: to allow port {MCP_PORT} from the ALB only.")
    elif alb_group:
        allow_ingress(
            clients,
            ctx.instance_security_group,
            MCP_PORT,
            "rancher-ai-mcp from the internal ALB",
            source_group=alb_group,
        )
        out.say(f"Security group {INSTANCE_NAME}: port {MCP_PORT} allowed from the ALB only.")
    return alb_group, gateway_group


def ensure_target_group(
    clients: Clients, ctx: Context, out: Out, plan: Plan, apply: bool
) -> str | None:
    try:
        found = clients.elbv2.describe_target_groups(Names=[TARGET_GROUP_NAME])["TargetGroups"]
    except ClientError as error:
        if _code(error) != "TargetGroupNotFound":
            raise
        found = []
    if found:
        plan.have()
        arn = str(found[0]["TargetGroupArn"])
    elif not apply:
        plan.need(f"target group {TARGET_GROUP_NAME}")
        out.say(f"Target group {TARGET_GROUP_NAME}: to create (HTTP {MCP_PORT}).")
        return None
    else:
        arn = clients.elbv2.create_target_group(
            Name=TARGET_GROUP_NAME,
            Protocol="HTTP",
            Port=MCP_PORT,
            VpcId=ctx.vpc_id,
            TargetType="instance",
            HealthCheckProtocol="HTTP",
            HealthCheckPath="/",
            Matcher={"HttpCode": "200-499"},
            Tags=_tags(("Name", TARGET_GROUP_NAME), SPIKE_TAG),
        )["TargetGroups"][0]["TargetGroupArn"]
        out.say(f"Target group {TARGET_GROUP_NAME}: created.")
    if apply:
        clients.elbv2.register_targets(
            TargetGroupArn=arn, Targets=[{"Id": ctx.instance_id, "Port": MCP_PORT}]
        )
    return arn


def ensure_load_balancer(
    clients: Clients,
    ctx: Context,
    alb_group: str | None,
    out: Out,
    plan: Plan,
    apply: bool,
) -> tuple[str | None, str | None]:
    """Return the internal ALB's ARN and DNS name."""
    try:
        found = clients.elbv2.describe_load_balancers(Names=[ALB_NAME])["LoadBalancers"]
    except ClientError as error:
        if _code(error) != "LoadBalancerNotFound":
            raise
        found = []
    if found:
        plan.have()
        balancer = found[0]
        if balancer.get("Scheme") != "internal":
            raise SetupError(f"the load balancer {ALB_NAME} exists but is not internal")
        # ELBv2 reports each zone by name and subnet, not by zone ID, so compare subnets:
        # the first of ctx.alb_subnet_ids is the subnet in the instance's zone.
        subnets = [z.get("SubnetId") for z in balancer.get("AvailabilityZones", [])]
        if ctx.alb_subnet_ids[0] not in subnets:
            if not apply:
                plan.need(f"load balancer zones to include {ctx.instance_az_id}")
                out.say(f"Load balancer {ALB_NAME}: to add the instance's zone.")
            else:
                clients.elbv2.set_subnets(
                    LoadBalancerArn=balancer["LoadBalancerArn"], Subnets=ctx.alb_subnet_ids
                )
                out.say(f"Load balancer {ALB_NAME}: now also in the instance's zone.")
    elif not apply:
        plan.need(f"internal ALB {ALB_NAME}")
        out.say(f"Load balancer {ALB_NAME}: to create, internal, in {', '.join(ctx.alb_az_ids)}.")
        return None, None
    else:
        balancer = clients.elbv2.create_load_balancer(
            Name=ALB_NAME,
            Subnets=ctx.alb_subnet_ids,
            SecurityGroups=[alb_group],
            Scheme="internal",
            Type="application",
            IpAddressType="ipv4",
            Tags=_tags(("Name", ALB_NAME), SPIKE_TAG),
        )["LoadBalancers"][0]
        out.say(f"Load balancer {ALB_NAME}: created (internal); waiting until it is active ...")
    arn = str(balancer["LoadBalancerArn"])
    if apply:
        clients.elbv2.get_waiter("load_balancer_available").wait(LoadBalancerArns=[arn])
        clients.elbv2.modify_load_balancer_attributes(
            LoadBalancerArn=arn,
            Attributes=[
                {"Key": "routing.http.drop_invalid_header_fields.enabled", "Value": "false"}
            ],
        )
    return arn, str(balancer["DNSName"])


def ensure_listener(
    clients: Clients,
    balancer_arn: str | None,
    target_group_arn: str | None,
    certificate_arn: str | None,
    out: Out,
    plan: Plan,
    apply: bool,
) -> None:
    listeners = []
    if balancer_arn:
        listeners = clients.elbv2.describe_listeners(LoadBalancerArn=balancer_arn)["Listeners"]
    if any(listener["Port"] == 443 for listener in listeners):
        plan.have()
        return
    if not apply:
        plan.need("HTTPS listener on 443")
        out.say("Listener: to create, HTTPS 443 with the certificate, forwarding to the server.")
        return
    clients.elbv2.create_listener(
        LoadBalancerArn=balancer_arn,
        Protocol="HTTPS",
        Port=443,
        SslPolicy=SSL_POLICY,
        Certificates=[{"CertificateArn": certificate_arn}],
        DefaultActions=[{"Type": "forward", "TargetGroupArn": target_group_arn}],
    )
    out.say("Listener: HTTPS 443 created.")


def wait_healthy(clients: Clients, ctx: Context, target_group_arn: str, out: Out) -> None:
    out.say("Target group: waiting until the server is healthy behind the ALB ...")
    try:
        clients.elbv2.get_waiter("target_in_service").wait(
            TargetGroupArn=target_group_arn,
            Targets=[{"Id": ctx.instance_id, "Port": MCP_PORT}],
            WaiterConfig={"Delay": 10, "MaxAttempts": 30},
        )
    except Exception as error:  # botocore WaiterError
        raise SetupError(f"the server did not turn healthy behind the ALB: {error}") from error
    out.say("Target group: healthy.")


def ensure_provider(
    clients: Clients, seams: Seams, out: Out, plan: Plan, apply: bool
) -> tuple[str | None, str | None]:
    """Return the API key credential provider's ARN and its secret's ARN."""
    try:
        found = clients.agentcore.get_api_key_credential_provider(name=PROVIDER_NAME)
    except ClientError as error:
        if _code(error) != "ResourceNotFoundException":
            raise
        found = None
    if not apply:
        if found:
            plan.have()
            out.say(f"Credential provider {PROVIDER_NAME}: exists (apply refreshes its key).")
            return str(found["credentialProviderArn"]), str(found["apiKeySecretArn"]["secretArn"])
        plan.need(f"API key credential provider {PROVIDER_NAME}")
        out.say(f"Credential provider {PROVIDER_NAME}: to create with sre-agent's token.")
        return None, None
    token = seams.keychain_token()
    if not token:
        raise SetupError(
            f"no {KEYCHAIN_TOKEN_ACCOUNT} in the Keychain; run configure_spike_rancher.py first"
        )
    out.hide(token, "[redacted]")
    if found:
        result = clients.agentcore.update_api_key_credential_provider(
            name=PROVIDER_NAME, apiKey=token
        )
        out.say(f"Credential provider {PROVIDER_NAME}: key refreshed from the Keychain.")
    else:
        result = clients.agentcore.create_api_key_credential_provider(
            name=PROVIDER_NAME,
            apiKey=token,
            tags={"Name": PROVIDER_NAME, SPIKE_TAG[0]: SPIKE_TAG[1]},
        )
        out.say(f"Credential provider {PROVIDER_NAME}: created with sre-agent's token.")
    return str(result["credentialProviderArn"]), str(result["apiKeySecretArn"]["secretArn"])


def role_documents(
    account: str, provider_arn: str, secret_arn: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The gateway role's trust policy and its one inline policy (AgentCore's documented set)."""
    base = f"arn:aws:bedrock-agentcore:{REGION}:{account}"
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"{base}:gateway/{GATEWAY_NAME}-*"},
                },
            }
        ],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "WorkloadAccessToken",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:GetWorkloadAccessToken",
                "Resource": [
                    f"{base}:workload-identity-directory/default",
                    f"{base}:workload-identity-directory/default/workload-identity/{GATEWAY_NAME}-*",
                ],
            },
            {
                "Sid": "RancherTokenFromTheVault",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:GetResourceApiKey",
                # AgentCore checks this action against the gateway's own workload identity as
                # well as the provider (CloudTrail, 2026-11-14); its documented example omits that.
                "Resource": sorted(
                    {
                        provider_arn,
                        f"{base}:token-vault/default",
                        f"{base}:token-vault/default/apikeycredentialprovider/{PROVIDER_NAME}",
                        f"{base}:workload-identity-directory/default",
                        f"{base}:workload-identity-directory/default/workload-identity/{GATEWAY_NAME}-*",
                    }
                ),
            },
            {
                "Sid": "RancherTokenSecret",
                "Effect": "Allow",
                "Action": "secretsmanager:GetSecretValue",
                "Resource": secret_arn,
            },
        ],
    }
    return trust, policy


def ensure_role(
    clients: Clients,
    ctx: Context,
    provider_arn: str | None,
    secret_arn: str | None,
    seams: Seams,
    out: Out,
    plan: Plan,
    apply: bool,
) -> str | None:
    try:
        role = clients.iam.get_role(RoleName=ROLE_NAME)["Role"]
    except ClientError as error:
        if _code(error) != "NoSuchEntity":
            raise
        role = None
    if not apply:
        if role:
            plan.have()
            return str(role["Arn"])
        plan.need(f"IAM role {ROLE_NAME}")
        out.say(f"Role {ROLE_NAME}: to create; it may read only the rancher-spike token.")
        return None
    if provider_arn is None or secret_arn is None:
        raise SetupError("the credential provider is missing")
    trust, policy = role_documents(ctx.account, provider_arn, secret_arn)
    if role is None:
        role = clients.iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Spike A, A5: AgentCore Gateway rancher-spike reads the Rancher token",
            Tags=_tags(("Name", ROLE_NAME), SPIKE_TAG),
        )["Role"]
        out.say(f"Role {ROLE_NAME}: created.")
        created = True
    else:
        clients.iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))
        created = False
    clients.iam.put_role_policy(
        RoleName=ROLE_NAME, PolicyName=ROLE_POLICY_NAME, PolicyDocument=json.dumps(policy)
    )
    if created:
        out.say("Role: waiting 15 seconds for IAM to propagate it ...")
        seams.sleep(15)
    return str(role["Arn"])


def find_gateway(clients: Clients) -> dict[str, Any] | None:
    token: str | None = None
    while True:
        page = clients.agentcore.list_gateways(**({"nextToken": token} if token else {}))
        for item in page["items"]:
            if item["name"] == GATEWAY_NAME:
                return dict(item)
        token = page.get("nextToken")
        if not token:
            return None


def wait_status(
    read: Callable[[], dict[str, Any]], what: str, seams: Seams, out: Out, minutes: float = 15
) -> dict[str, Any]:
    """Poll until the status leaves CREATING, UPDATING or SYNCHRONIZING."""
    deadline = seams.monotonic() + minutes * 60
    while True:
        current = read()
        status = str(current["status"])
        if status not in ("CREATING", "UPDATING", "SYNCHRONIZING"):
            return current
        if seams.monotonic() >= deadline:
            raise SetupError(f"{what} is still {status} after {minutes:.0f} minutes")
        seams.sleep(10)


def ensure_gateway(
    clients: Clients, role_arn: str | None, seams: Seams, out: Out, plan: Plan, apply: bool
) -> dict[str, Any] | None:
    found = find_gateway(clients)
    if found is None and not apply:
        plan.need(f"gateway {GATEWAY_NAME}")
        out.say(f"Gateway {GATEWAY_NAME}: to create, MCP, signed in with IAM (AWS_IAM).")
        return None
    if found is None:
        attempts = 0
        while True:
            try:
                created = clients.agentcore.create_gateway(
                    name=GATEWAY_NAME,
                    description="Spike A, A5: rancher-ai-mcp through a private endpoint",
                    roleArn=role_arn,
                    protocolType="MCP",
                    authorizerType="AWS_IAM",
                    tags={"Name": GATEWAY_NAME, SPIKE_TAG[0]: SPIKE_TAG[1]},
                )
                break
            except ClientError as error:
                attempts += 1
                if _code(error) != "ValidationException" or attempts >= 6:
                    raise
                out.say("Gateway: the new role is not usable yet; trying again in 10 seconds ...")
                seams.sleep(10)
        gateway_id = str(created["gatewayId"])
        out.say(f"Gateway {GATEWAY_NAME}: created; waiting until it is ready ...")
    else:
        plan.have()
        gateway_id = str(found["gatewayId"])
    gateway = wait_status(
        lambda: dict(clients.agentcore.get_gateway(gatewayIdentifier=gateway_id)),
        "the gateway",
        seams,
        out,
    )
    if gateway["status"] != "READY":
        reasons = "; ".join(gateway.get("statusReasons") or ["no reason given"])
        raise SetupError(f"the gateway is {gateway['status']}: {reasons}")
    if gateway.get("authorizerType") != "AWS_IAM":
        raise SetupError("the gateway exists but does not use AWS_IAM sign-in")
    out.say(f"Gateway {GATEWAY_NAME}: ready.")
    return gateway


def target_request(
    ctx: Context,
    provider_arn: str,
    gateway_group: str,
    routing_domain: str,
) -> dict[str, Any]:
    """The MCP target: our hostname for TLS, routed privately to the internal ALB."""
    return {
        "name": TARGET_NAME,
        "description": "rancher-ai-mcp, read tools only, behind the internal ALB",
        "targetConfiguration": {"mcp": {"mcpServer": {"endpoint": ctx.endpoint}}},
        "credentialProviderConfigurations": [
            {
                "credentialProviderType": "API_KEY",
                "credentialProvider": {
                    "apiKeyCredentialProvider": {
                        "providerArn": provider_arn,
                        "credentialParameterName": TOKEN_HEADER,
                        "credentialLocation": "HEADER",
                    }
                },
            }
        ],
        "privateEndpoint": {
            "managedVpcResource": {
                "vpcIdentifier": ctx.vpc_id,
                "subnetIds": ctx.endpoint_subnet_ids,
                "endpointIpAddressType": "IPV4",
                "securityGroupIds": [gateway_group],
                "routingDomain": routing_domain,
                "tags": {"Name": HOST_LABEL, SPIKE_TAG[0]: SPIKE_TAG[1]},
            }
        },
    }


def ensure_target(
    clients: Clients,
    ctx: Context,
    gateway: dict[str, Any] | None,
    provider_arn: str | None,
    gateway_group: str | None,
    routing_domain: str | None,
    seams: Seams,
    out: Out,
    plan: Plan,
    apply: bool,
) -> dict[str, Any] | None:
    existing = None
    if gateway:
        items = clients.agentcore.list_gateway_targets(gatewayIdentifier=gateway["gatewayId"])
        existing = next((t for t in items["items"] if t["name"] == TARGET_NAME), None)
    if not apply:
        if existing:
            plan.have()
            out.say(f"Target {TARGET_NAME}: {existing['status']}.")
            return dict(existing)
        plan.need(f"target {TARGET_NAME}")
        out.say(
            f"Target {TARGET_NAME}: to create, https://mcp-spike.<domain>/mcp through a managed "
            f"private endpoint, with the token in the {TOKEN_HEADER} header."
        )
        return None
    if not (gateway and provider_arn and gateway_group and routing_domain):
        raise SetupError("a resource the target needs is missing")
    request = target_request(ctx, provider_arn, gateway_group, routing_domain)
    gateway_id = str(gateway["gatewayId"])
    if existing is None:
        target_id = str(
            clients.agentcore.create_gateway_target(gatewayIdentifier=gateway_id, **request)[
                "targetId"
            ]
        )
        out.say(
            f"Target {TARGET_NAME}: created; AgentCore builds the private endpoint and reads "
            "the server's tools (several minutes) ..."
        )
    else:
        target_id = str(existing["targetId"])
        if existing["status"] in BROKEN_TARGET_STATES:
            clients.agentcore.update_gateway_target(
                gatewayIdentifier=gateway_id, targetId=target_id, **request
            )
            out.say(f"Target {TARGET_NAME}: was {existing['status']}; updated to try again ...")
    target = wait_status(
        lambda: dict(
            clients.agentcore.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        ),
        "the target",
        seams,
        out,
        minutes=20,
    )
    if target["status"] != "READY":
        reasons = "; ".join(target.get("statusReasons") or ["no reason given"])
        raise SetupError(f"the target is {target['status']}: {reasons}")
    out.say(f"Target {TARGET_NAME}: ready.")
    return target


def save_state(gateway: dict[str, Any], target: dict[str, Any], out: Out) -> Path:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = STATE_DIR / "gateway.json"
    path.write_text(
        json.dumps(
            {
                "gatewayId": gateway["gatewayId"],
                "gatewayUrl": gateway.get("gatewayUrl"),
                "targetId": target["targetId"],
                "targetName": TARGET_NAME,
                "region": REGION,
            },
            indent=1,
        )
        + "\n"
    )
    path.chmod(0o600)
    return path


def run(clients: Clients, seams: Seams, out: Out, apply: bool) -> int:
    plan = Plan()
    ctx = discover(clients, out)
    certificate = ensure_certificate(clients, ctx, seams, out, plan, apply)
    ensure_mcp_server(ctx, seams, out, plan, apply)
    alb_group, gateway_group = ensure_network(clients, ctx, out, plan, apply)
    target_group = ensure_target_group(clients, ctx, out, plan, apply)
    balancer_arn, balancer_dns = ensure_load_balancer(clients, ctx, alb_group, out, plan, apply)
    if apply and certificate:
        wait_certificate(clients, certificate, out)
    ensure_listener(clients, balancer_arn, target_group, certificate, out, plan, apply)
    if apply and target_group:
        wait_healthy(clients, ctx, target_group, out)
    try:
        provider_arn, secret_arn = ensure_provider(clients, seams, out, plan, apply)
        role_arn = ensure_role(clients, ctx, provider_arn, secret_arn, seams, out, plan, apply)
        gateway = ensure_gateway(clients, role_arn, seams, out, plan, apply)
        target = ensure_target(
            clients,
            ctx,
            gateway,
            provider_arn,
            gateway_group,
            balancer_dns,
            seams,
            out,
            plan,
            apply,
        )
    except ClientError as error:
        if apply or not _code(error).startswith("AccessDenied"):
            raise
        out.say(
            "AgentCore: these credentials cannot read AgentCore or IAM here; apply creates the "
            "credential provider, role, gateway and target as needed."
        )
        gateway = target = None
    if not apply:
        out.say(
            f"Plan: {len(plan.to_change)} to create or start, {plan.in_place} already in place."
        )
        return 0
    if gateway is None or target is None:
        raise SetupError("the gateway or its target is missing after apply")
    path = save_state(gateway, target, out)
    out.say(f"Saved the gateway's IDs to {path}.")
    out.say(
        f"A5 is set up: gateway {GATEWAY_NAME} is ready, and its target {TARGET_NAME} is ready."
    )
    return 0


def set_debug(clients: Clients, seams: Seams, out: Out, on: bool) -> int:
    """Turn the gateway's detailed error messages on (DEBUG) or back off (generic)."""
    found = find_gateway(clients)
    if found is None:
        raise SetupError(f"no gateway {GATEWAY_NAME}; run apply first")
    gateway_id = str(found["gatewayId"])
    current = clients.agentcore.get_gateway(gatewayIdentifier=gateway_id)
    request: dict[str, Any] = {
        "gatewayIdentifier": gateway_id,
        "name": current["name"],
        "roleArn": current["roleArn"],
        "protocolType": current.get("protocolType", "MCP"),
        "authorizerType": current["authorizerType"],
    }
    if current.get("description"):
        request["description"] = current["description"]
    if on:
        request["exceptionLevel"] = "DEBUG"
    clients.agentcore.update_gateway(**request)
    gateway = wait_status(
        lambda: dict(clients.agentcore.get_gateway(gatewayIdentifier=gateway_id)),
        "the gateway",
        seams,
        out,
    )
    if gateway["status"] != "READY":
        reasons = "; ".join(gateway.get("statusReasons") or ["no reason given"])
        raise SetupError(f"the gateway is {gateway['status']}: {reasons}")
    state = "on: errors now carry their details" if on else "off: errors are generic again"
    out.say(f"Gateway {GATEWAY_NAME}: detailed errors {state}.")
    return 0


def keychain_token() -> str | None:
    result = subprocess.run(  # noqa: S603 - fixed program and arguments
        [
            SECURITY,
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_TOKEN_ACCOUNT,
            "-w",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.rstrip("\n")
    return value if result.returncode == 0 and value else None


def ssh_runner(key: Path, out: Out) -> Callable[[str, str], str]:
    """Copy the script to the instance, run it with no stdin, relay its progress lines."""

    def run_on_instance(public_ip: str, script: str) -> str:
        command = [
            SSH,
            "-i",
            str(key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={STATE_DIR / 'known_hosts'}",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            f"ubuntu@{public_ip}",
            "cat > /tmp/spike-a5-setup.sh && bash /tmp/spike-a5-setup.sh < /dev/null",
        ]
        process = subprocess.Popen(  # noqa: S603 - fixed program; the address comes from EC2
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if not (process.stdin and process.stdout and process.stderr):
            raise SetupError("ssh started without its pipes")
        watchdog = threading.Timer(2700, process.kill)
        watchdog.start()
        lines: list[str] = []
        try:
            process.stdin.write(script)
            process.stdin.close()
            for line in process.stdout:
                lines.append(line.rstrip())
                if line.startswith("progress: "):
                    out.say(f"Server: {line.removeprefix('progress: ').rstrip()}.")
            process.wait()
            errors = process.stderr.read()
        finally:
            watchdog.cancel()
        if process.returncode != 0:
            tail = [x for x in lines if not x.startswith("progress: ")][-15:]
            tail += errors.strip().splitlines()[-3:]
            raise SetupError(
                f"the instance step failed (exit {process.returncode}): "
                + (" | ".join(tail) or "no message")
            )
        return "\n".join(lines)

    return run_on_instance


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Spike A, A5: rancher-ai-mcp through AgentCore Gateway, privately."
    )
    parser.add_argument("mode", choices=("plan", "apply", "debug-on", "debug-off"))
    parser.add_argument("--key", type=Path, default=Path.home() / ".ssh" / "rancher-spike.pem")
    args = parser.parse_args(argv)
    out = Out()
    clients = Clients.from_session(boto3.Session(region_name=REGION))
    seams = Seams(
        keychain_token=keychain_token, run_on_instance=ssh_runner(args.key.expanduser(), out)
    )
    try:
        if args.mode.startswith("debug-"):
            return set_debug(clients, seams, out, on=args.mode == "debug-on")
        return run(clients, seams, out, apply=args.mode == "apply")
    except SetupError as error:
        out.say(f"setup_gateway: {error}. Fix the cause and run the same command again.")
        return 1
    except (ClientError, BotoCoreError) as error:
        out.say(f"setup_gateway: an AWS call failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
