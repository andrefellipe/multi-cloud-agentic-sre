#!/usr/bin/env python3
"""Spike A, A6: remove what A1 to A5 created, in dependency order.

Run from the repository root, in your admin terminal:

    uv run python tools/spikes/spike-a/teardown.py plan                   # read-only: what is left
    uv run python tools/spikes/spike-a/teardown.py apply                  # delete all A1-A5 created
    uv run python tools/spikes/spike-a/teardown.py plan --keep-instance   # A5's resources only
    uv run python tools/spikes/spike-a/teardown.py apply --keep-instance  # keep A1-A4 to test more

Order. Each step skips what is already gone, waits within a limit, and retries the
dependency errors AWS returns while an earlier deletion settles:

1. AgentCore: target rancher (until it is gone, because AgentCore then removes the managed
   VPC Lattice resource gateway and its network interfaces), gateway rancher-spike, and the
   API key credential provider rancher-spike with its secret.
2. IAM role rancher-spike-gateway and its inline policy.
3. The internal ALB mcp-spike: its listener, the ALB itself (until it is deleted), and the
   target group mcp-spike.
4. The port 9092 rule on security group rancher-spike, which names mcp-spike-alb and would
   keep it from being deleted, then the security groups mcp-spike-alb and mcp-spike-gateway.
5. The ACM certificate for mcp-spike.<domain>, only once the ALB is gone, and its DNS
   validation record in the public zone.
6. With --keep-instance: the rancher-mcp container on the instance, over SSH. Stop here.
7. Otherwise: terminate the rancher-spike instance, delete its security group and the key
   pair rancher-spike, then the default VPC that A1 created (internet gateway and subnets
   first), but only while nothing else is in it.
8. Otherwise, on this Mac: the Keychain items (service rancher-spike), the files in
   ~/.rancher-spike/, ~/.ssh/rancher-spike.pem and the local image of rancher-ai-mcp.

It touches only what the spike created: the names and tags setup_gateway.py uses, in the
default VPC. It never looks at another VPC. It prints no domain, account ID, IP address or
secret.

Exit status: 0 when the plan or the teardown finished, 1 when a step failed (fix the cause
and run it again), 2 on a usage error.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, WaiterError

HERE = Path(__file__).resolve().parent


def _load_setup() -> ModuleType:
    """Reuse setup_gateway.py's names and helpers (this folder is not a package)."""
    path = HERE / "setup_gateway.py"
    loaded = sys.modules.get("setup_gateway")
    if loaded is not None and Path(str(loaded.__file__)).resolve() == path:
        return loaded
    spec = importlib.util.spec_from_file_location("setup_gateway", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sg = _load_setup()

KEYCHAIN_ACCOUNTS = ("admin", "sre-agent", "sre-agent-token")
STATE_FILES = ("gateway.json", "rancher-url", "rancher-ca.pem", "known_hosts")
LIVE_STATES = ["pending", "running", "stopping", "stopped", "shutting-down"]
REMOTE_REMOVE = "sudo docker rm -f rancher-mcp >/dev/null 2>&1 || true\necho removed\n"
DOCKER = "docker"


class TeardownError(Exception):
    """A step failed or must not go on. The message is printed only after redaction."""


@dataclass(frozen=True)
class Seams:
    """What the script reaches outside AWS's APIs; tests replace each one."""

    run_on_instance: Callable[[str, str], str]
    keychain_has: Callable[[str], bool]
    delete_keychain_item: Callable[[str], bool]
    image_present: Callable[[], bool | None]
    remove_image: Callable[[], bool]
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class Paths:
    """Local files the spike wrote. Printed relative to home, as ~/..."""

    home: Path
    state_dir: Path
    ssh_key: Path

    def show(self, path: Path) -> str:
        try:
            return "~/" + str(path.relative_to(self.home))
        except ValueError:
            return path.name


@dataclass
class World:
    """What the spike left, read once at the start."""

    account: str
    domain: str | None
    zone_id: str | None
    vpc: dict[str, Any] | None
    instance: dict[str, Any] | None


@dataclass
class Todo:
    """Plan mode collects one line per resource; apply mode counts its actions."""

    items: list[str] = field(default_factory=list)
    done: int = 0


def _code(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def note(todo: Todo, out: Any, apply: bool, plan_line: str) -> None:
    """In plan mode, record and print one resource that apply would remove."""
    if not apply:
        todo.items.append(plan_line)
        out.say(plan_line)


def did(todo: Todo, out: Any, line: str) -> None:
    todo.done += 1
    out.say(line)


def retry(
    action: Callable[[], Any],
    codes: Sequence[str],
    what: str,
    seams: Seams,
    out: Any,
    minutes: float,
    every: float = 15.0,
) -> Any:
    """Run `action`, retrying while AWS answers one of `codes`, for up to `minutes`."""
    deadline = seams.monotonic() + minutes * 60
    waited = False
    while True:
        try:
            return action()
        except ClientError as error:
            if _code(error) not in codes or seams.monotonic() >= deadline:
                raise
            if not waited:
                out.say(f"{what}: AWS still holds it ({_code(error)}); waiting ...")
                waited = True
            seams.sleep(every)


def wait_gone(read: Callable[[], dict[str, Any]], what: str, seams: Seams, minutes: float) -> None:
    """Poll an AgentCore resource until reading it answers ResourceNotFoundException."""
    deadline = seams.monotonic() + minutes * 60
    while True:
        try:
            current = read()
        except ClientError as error:
            if _code(error) == "ResourceNotFoundException":
                return
            raise
        status = str(current.get("status", ""))
        if status == "FAILED":
            reasons = "; ".join(current.get("statusReasons") or ["no reason given"])
            raise TeardownError(f"{what} failed to delete: {reasons}")
        if seams.monotonic() >= deadline:
            raise TeardownError(f"{what} is still {status} after {minutes:.0f} minutes")
        seams.sleep(10)


# Discovery -----------------------------------------------------------------------


def discover(clients: Any, out: Any) -> World:
    """Read what the spike may have left. Read-only, and it tolerates what is gone."""
    account = str(clients.sts.get_caller_identity()["Account"])
    domain: str | None
    try:
        domain = str(clients.ssm.get_parameter(Name=sg.DOMAIN_PARAMETER)["Parameter"]["Value"])
    except ClientError as error:
        out.say(
            f"Domain: cannot read {sg.DOMAIN_PARAMETER} ({_code(error)}); skipping the certificate."
        )
        domain = None
    zone_id = None
    if domain:
        out.hide(domain, "<domain>")
        zones = clients.route53.list_hosted_zones_by_name(DNSName=domain)["HostedZones"]
        public = [
            z
            for z in zones
            if z["Name"].rstrip(".") == domain and not z.get("Config", {}).get("PrivateZone")
        ]
        zone_id = public[0]["Id"].split("/")[-1] if public else None
    vpcs = clients.ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    vpc = vpcs[0] if vpcs else None
    instance = None
    if vpc:
        reservations = clients.ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [sg.INSTANCE_NAME]},
                {"Name": "vpc-id", "Values": [vpc["VpcId"]]},
                {"Name": "instance-state-name", "Values": LIVE_STATES},
            ]
        )["Reservations"]
        instances = [i for r in reservations for i in r["Instances"]]
        if len(instances) > 1:
            raise TeardownError(
                f"found {len(instances)} {sg.INSTANCE_NAME} instances; expected one"
            )
        instance = instances[0] if instances else None
        if instance:
            out.hide(str(instance.get("PublicIpAddress", "")), "<instance-ip>")
            out.hide(str(instance.get("PrivateIpAddress", "")), "<private-ip>")
    return World(account=account, domain=domain, zone_id=zone_id, vpc=vpc, instance=instance)


# 1. AgentCore ----------------------------------------------------------------------


def remove_agentcore(clients: Any, seams: Seams, out: Any, todo: Todo, apply: bool) -> None:
    gateway = sg.find_gateway(clients)
    if gateway:
        gateway_id = str(gateway["gatewayId"])
        targets: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            page = clients.agentcore.list_gateway_targets(
                gatewayIdentifier=gateway_id, **({"nextToken": token} if token else {})
            )
            targets.extend(page["items"])
            token = page.get("nextToken")
            if not token:
                break
        for target in targets:
            name = target["name"]
            note(
                todo,
                out,
                apply,
                f"To delete: AgentCore target {name} ({target['status']}) "
                "and its private endpoint.",
            )
            if apply:
                target_id = str(target["targetId"])
                try:
                    clients.agentcore.delete_gateway_target(
                        gatewayIdentifier=gateway_id, targetId=target_id
                    )
                except ClientError as error:
                    if _code(error) not in ("ResourceNotFoundException", "ConflictException"):
                        raise
                out.say(
                    f"AgentCore target {name}: deleting; AgentCore removes its private endpoint ..."
                )
                wait_gone(
                    functools.partial(
                        clients.agentcore.get_gateway_target,
                        gatewayIdentifier=gateway_id,
                        targetId=target_id,
                    ),
                    f"the target {name}",
                    seams,
                    minutes=20,
                )
                did(todo, out, f"Deleted: AgentCore target {name}.")
        note(todo, out, apply, f"To delete: AgentCore gateway {sg.GATEWAY_NAME}.")
        if apply:
            retry(
                lambda: clients.agentcore.delete_gateway(gatewayIdentifier=gateway_id),
                ("ConflictException",),
                f"Gateway {sg.GATEWAY_NAME}",
                seams,
                out,
                minutes=10,
                every=10,
            )
            wait_gone(
                lambda: dict(clients.agentcore.get_gateway(gatewayIdentifier=gateway_id)),
                f"the gateway {sg.GATEWAY_NAME}",
                seams,
                minutes=10,
            )
            did(todo, out, f"Deleted: AgentCore gateway {sg.GATEWAY_NAME}.")
    try:
        clients.agentcore.get_api_key_credential_provider(name=sg.PROVIDER_NAME)
    except ClientError as error:
        if _code(error) != "ResourceNotFoundException":
            raise
        return
    note(todo, out, apply, f"To delete: credential provider {sg.PROVIDER_NAME} and its secret.")
    if apply:
        try:
            clients.agentcore.delete_api_key_credential_provider(name=sg.PROVIDER_NAME)
        except ClientError as error:
            if _code(error) != "ResourceNotFoundException":
                raise
        did(todo, out, f"Deleted: credential provider {sg.PROVIDER_NAME} and its secret.")


# 2. IAM --------------------------------------------------------------------------


def remove_role(clients: Any, out: Any, todo: Todo, apply: bool) -> None:
    try:
        clients.iam.get_role(RoleName=sg.ROLE_NAME)
    except ClientError as error:
        if _code(error) != "NoSuchEntity":
            raise
        return
    note(todo, out, apply, f"To delete: IAM role {sg.ROLE_NAME} and its inline policy.")
    if not apply:
        return
    for name in clients.iam.list_role_policies(RoleName=sg.ROLE_NAME)["PolicyNames"]:
        clients.iam.delete_role_policy(RoleName=sg.ROLE_NAME, PolicyName=name)
    attached = clients.iam.list_attached_role_policies(RoleName=sg.ROLE_NAME)["AttachedPolicies"]
    for policy in attached:
        clients.iam.detach_role_policy(RoleName=sg.ROLE_NAME, PolicyArn=policy["PolicyArn"])
    clients.iam.delete_role(RoleName=sg.ROLE_NAME)
    did(todo, out, f"Deleted: IAM role {sg.ROLE_NAME}.")


# 3. Load balancer ------------------------------------------------------------------


def find_load_balancer(clients: Any, world: World) -> dict[str, Any] | None:
    try:
        found = clients.elbv2.describe_load_balancers(Names=[sg.ALB_NAME])["LoadBalancers"]
    except ClientError as error:
        if _code(error) != "LoadBalancerNotFound":
            raise
        return None
    balancer = dict(found[0])
    if world.vpc is None or balancer.get("VpcId") != world.vpc["VpcId"]:
        raise TeardownError(f"a load balancer named {sg.ALB_NAME} exists outside the default VPC")
    return balancer


def remove_load_balancer(
    clients: Any, world: World, seams: Seams, out: Any, todo: Todo, apply: bool
) -> None:
    balancer = find_load_balancer(clients, world)
    if balancer:
        arn = str(balancer["LoadBalancerArn"])
        for listener in clients.elbv2.describe_listeners(LoadBalancerArn=arn)["Listeners"]:
            note(
                todo,
                out,
                apply,
                f"To delete: {listener['Protocol']} listener on {listener['Port']}.",
            )
            if apply:
                clients.elbv2.delete_listener(ListenerArn=listener["ListenerArn"])
                did(todo, out, f"Deleted: {listener['Protocol']} listener on {listener['Port']}.")
        note(todo, out, apply, f"To delete: internal load balancer {sg.ALB_NAME}.")
        if apply:
            clients.elbv2.delete_load_balancer(LoadBalancerArn=arn)
            out.say(f"Load balancer {sg.ALB_NAME}: deleting ...")
            try:
                clients.elbv2.get_waiter("load_balancers_deleted").wait(
                    LoadBalancerArns=[arn], WaiterConfig={"Delay": 15, "MaxAttempts": 40}
                )
            except WaiterError as error:
                raise TeardownError(f"the load balancer was not deleted: {error}") from error
            did(todo, out, f"Deleted: internal load balancer {sg.ALB_NAME}.")
    try:
        groups = clients.elbv2.describe_target_groups(Names=[sg.TARGET_GROUP_NAME])["TargetGroups"]
    except ClientError as error:
        if _code(error) != "TargetGroupNotFound":
            raise
        groups = []
    for group in groups:
        note(todo, out, apply, f"To delete: target group {sg.TARGET_GROUP_NAME}.")
        if apply:
            retry(
                functools.partial(
                    clients.elbv2.delete_target_group, TargetGroupArn=group["TargetGroupArn"]
                ),
                ("ResourceInUse",),
                f"Target group {sg.TARGET_GROUP_NAME}",
                seams,
                out,
                minutes=5,
            )
            did(todo, out, f"Deleted: target group {sg.TARGET_GROUP_NAME}.")


# 4. Security groups ----------------------------------------------------------------


def find_group(clients: Any, world: World, name: str) -> dict[str, Any] | None:
    if world.vpc is None:
        return None
    found = clients.ec2.describe_security_groups(
        Filters=[
            {"Name": "vpc-id", "Values": [world.vpc["VpcId"]]},
            {"Name": "group-name", "Values": [name]},
        ]
    )["SecurityGroups"]
    return dict(found[0]) if found else None


def delete_group(
    clients: Any, group: dict[str, Any], seams: Seams, out: Any, todo: Todo, minutes: float
) -> None:
    retry(
        lambda: clients.ec2.delete_security_group(GroupId=group["GroupId"]),
        ("DependencyViolation", "InvalidGroup.InUse"),
        f"Security group {group['GroupName']}",
        seams,
        out,
        minutes=minutes,
        every=20,
    )
    did(todo, out, f"Deleted: security group {group['GroupName']}.")


def remove_spike_groups(
    clients: Any, world: World, seams: Seams, out: Any, todo: Todo, apply: bool
) -> None:
    alb_group = find_group(clients, world, sg.ALB_SECURITY_GROUP)
    instance_group = find_group(clients, world, sg.INSTANCE_NAME)
    if alb_group and instance_group:
        # Revoke with the pair exactly as AWS described it (owner and description included).
        rules = [
            {
                "IpProtocol": rule["IpProtocol"],
                "FromPort": rule["FromPort"],
                "ToPort": rule["ToPort"],
                "UserIdGroupPairs": [
                    pair
                    for pair in rule.get("UserIdGroupPairs", [])
                    if pair.get("GroupId") == alb_group["GroupId"]
                ],
            }
            for rule in instance_group.get("IpPermissions", [])
            if any(
                p.get("GroupId") == alb_group["GroupId"] for p in rule.get("UserIdGroupPairs", [])
            )
        ]
        for rule in rules:
            line = f"port {rule['FromPort']} rule on security group {sg.INSTANCE_NAME}"
            note(todo, out, apply, f"To remove: {line}, from {sg.ALB_SECURITY_GROUP}.")
            if apply:
                clients.ec2.revoke_security_group_ingress(
                    GroupId=instance_group["GroupId"], IpPermissions=[rule]
                )
                did(todo, out, f"Removed: {line}.")
    for name in (sg.ALB_SECURITY_GROUP, sg.GATEWAY_SECURITY_GROUP):
        group = find_group(clients, world, name)
        if group is None:
            continue
        note(todo, out, apply, f"To delete: security group {name}.")
        if apply:
            # The ALB's and the private endpoint's network interfaces take a few minutes to go.
            delete_group(clients, group, seams, out, todo, minutes=20)


# 5. Certificate --------------------------------------------------------------------


def find_certificates(clients: Any, fqdn: str) -> list[str]:
    arns = []
    for page in clients.acm.get_paginator("list_certificates").paginate():
        for summary in page["CertificateSummaryList"]:
            if summary.get("DomainName") == fqdn:
                arns.append(str(summary["CertificateArn"]))
    return arns


def find_record(clients: Any, zone_id: str, name: str, kind: str) -> dict[str, Any] | None:
    found = clients.route53.list_resource_record_sets(
        HostedZoneId=zone_id, StartRecordName=name, StartRecordType=kind, MaxItems="1"
    )["ResourceRecordSets"]
    for record in found:
        if (
            record["Name"].rstrip(".").lower() == name.rstrip(".").lower()
            and record["Type"] == kind
        ):
            return dict(record)
    return None


def remove_certificate(
    clients: Any, world: World, seams: Seams, out: Any, todo: Todo, apply: bool
) -> None:
    if not world.domain:
        return
    fqdn = f"{sg.HOST_LABEL}.{world.domain}"
    for arn in find_certificates(clients, fqdn):
        certificate = clients.acm.describe_certificate(CertificateArn=arn)["Certificate"]
        options = certificate.get("DomainValidationOptions") or [{}]
        validation = options[0].get("ResourceRecord")
        record = None
        if validation and world.zone_id:
            record = find_record(clients, world.zone_id, validation["Name"], validation["Type"])
        note(todo, out, apply, f"To delete: ACM certificate for {fqdn}.")
        if record:
            note(todo, out, apply, "To delete: its DNS validation record in the public zone.")
        if not apply:
            continue
        if find_load_balancer(clients, world) is not None:
            raise TeardownError(
                "the load balancer still exists, so the certificate is still in use"
            )
        retry(
            functools.partial(clients.acm.delete_certificate, CertificateArn=arn),
            ("ResourceInUseException",),
            "Certificate",
            seams,
            out,
            minutes=10,
        )
        did(todo, out, f"Deleted: ACM certificate for {fqdn}.")
        if record and world.zone_id:
            clients.route53.change_resource_record_sets(
                HostedZoneId=world.zone_id,
                ChangeBatch={
                    "Comment": "Spike A teardown: ACM validation for mcp-spike",
                    "Changes": [{"Action": "DELETE", "ResourceRecordSet": record}],
                },
            )
            did(todo, out, "Deleted: the certificate's DNS validation record.")


# 6. The server, when the instance stays ---------------------------------------------


def remove_server_container(world: World, seams: Seams, out: Any, todo: Todo, apply: bool) -> None:
    instance = world.instance
    if instance is None or instance.get("State", {}).get("Name") != "running":
        if instance is not None:
            out.say("Instance: not running, so the rancher-mcp container was left alone.")
        return
    note(todo, out, apply, "To remove: the rancher-mcp container on the instance, over SSH.")
    if apply:
        seams.run_on_instance(str(instance.get("PublicIpAddress", "")), REMOTE_REMOVE)
        did(todo, out, "Removed: the rancher-mcp container on the instance.")


# 7. Instance, its security group, key pair and the default VPC -----------------------


def remove_instance(
    clients: Any, world: World, seams: Seams, out: Any, todo: Todo, apply: bool
) -> None:
    instance = world.instance
    if instance:
        instance_id = str(instance["InstanceId"])
        note(todo, out, apply, f"To terminate: instance {instance_id} ({sg.INSTANCE_NAME}).")
        if apply:
            clients.ec2.terminate_instances(InstanceIds=[instance_id])
            out.say(f"Instance {instance_id}: terminating ...")
            try:
                clients.ec2.get_waiter("instance_terminated").wait(
                    InstanceIds=[instance_id], WaiterConfig={"Delay": 15, "MaxAttempts": 40}
                )
            except WaiterError as error:
                raise TeardownError(f"the instance did not terminate: {error}") from error
            did(todo, out, f"Terminated: instance {instance_id}.")
    group = find_group(clients, world, sg.INSTANCE_NAME)
    if group:
        note(todo, out, apply, f"To delete: security group {sg.INSTANCE_NAME}.")
        if apply:
            delete_group(clients, group, seams, out, todo, minutes=10)
    try:
        clients.ec2.describe_key_pairs(KeyNames=[sg.INSTANCE_NAME])
    except ClientError as error:
        if _code(error) != "InvalidKeyPair.NotFound":
            raise
        return
    note(todo, out, apply, f"To delete: key pair {sg.INSTANCE_NAME}.")
    if apply:
        clients.ec2.delete_key_pair(KeyName=sg.INSTANCE_NAME)
        did(todo, out, f"Deleted: key pair {sg.INSTANCE_NAME}.")


def vpc_blockers(
    clients: Any, vpc_id: str, ignore_instance: str | None, count_interfaces: bool
) -> list[str]:
    """What, besides the spike, still uses the default VPC.

    Network interfaces count only once the spike's own are meant to be gone (in apply,
    after the load balancer, the private endpoint and the instance were deleted).
    """
    vpc_filter = [{"Name": "vpc-id", "Values": [vpc_id]}]
    reservations = clients.ec2.describe_instances(
        Filters=[*vpc_filter, {"Name": "instance-state-name", "Values": LIVE_STATES}]
    )["Reservations"]
    others = [
        i["InstanceId"]
        for r in reservations
        for i in r["Instances"]
        if i["InstanceId"] != ignore_instance
    ]
    blockers = []
    if others:
        blockers.append(f"{len(others)} other instance(s)")
    if count_interfaces:
        interfaces = clients.ec2.describe_network_interfaces(Filters=vpc_filter)[
            "NetworkInterfaces"
        ]
        # The spike instance's own interface goes with the instance.
        foreign_interfaces = [
            n
            for n in interfaces
            if not ignore_instance
            or (n.get("Attachment") or {}).get("InstanceId") != ignore_instance
        ]
        if foreign_interfaces:
            blockers.append(f"{len(foreign_interfaces)} network interface(s)")
    groups = clients.ec2.describe_security_groups(Filters=vpc_filter)["SecurityGroups"]
    spike_groups = (sg.INSTANCE_NAME, sg.ALB_SECURITY_GROUP, sg.GATEWAY_SECURITY_GROUP, "default")
    foreign = [g for g in groups if g["GroupName"] not in spike_groups]
    if foreign:
        blockers.append(f"{len(foreign)} security group(s) the spike did not create")
    tables = clients.ec2.describe_route_tables(Filters=vpc_filter)["RouteTables"]
    custom = [t for t in tables if not any(a.get("Main") for a in t.get("Associations", []))]
    if custom:
        blockers.append(f"{len(custom)} route table(s) the spike did not create")
    return blockers


def remove_default_vpc(
    clients: Any, world: World, seams: Seams, out: Any, todo: Todo, apply: bool
) -> None:
    vpc = world.vpc
    if vpc is None:
        return
    if not vpc.get("IsDefault"):
        raise TeardownError("refusing to delete a VPC that is not the default VPC")
    vpc_id = str(vpc["VpcId"])
    ignore = str(world.instance["InstanceId"]) if world.instance else None
    blockers = vpc_blockers(clients, vpc_id, ignore, count_interfaces=apply)
    if blockers and apply:
        # Interfaces of a terminated instance, the ALB or the endpoint can take minutes to go.
        deadline = seams.monotonic() + 10 * 60
        while blockers and all("network interface" in b for b in blockers):
            if seams.monotonic() >= deadline:
                break
            out.say("Default VPC: waiting for AWS to release network interfaces ...")
            seams.sleep(30)
            blockers = vpc_blockers(clients, vpc_id, ignore, count_interfaces=True)
    if blockers:
        message = f"the default VPC still has {', '.join(blockers)}, so it stays"
        if apply:
            raise TeardownError(message)
        out.say(f"Default VPC: kept, because it has {', '.join(blockers)}.")
        return
    subnets = clients.ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])[
        "Subnets"
    ]
    gateways = clients.ec2.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
    )["InternetGateways"]
    note(
        todo,
        out,
        apply,
        f"To delete: default VPC {vpc['CidrBlock']} with {len(gateways)} internet gateway(s) "
        f"and {len(subnets)} subnets (A1 created it; the account had none).",
    )
    if not apply:
        return
    for gateway in gateways:
        clients.ec2.detach_internet_gateway(
            InternetGatewayId=gateway["InternetGatewayId"], VpcId=vpc_id
        )
        clients.ec2.delete_internet_gateway(InternetGatewayId=gateway["InternetGatewayId"])
    for subnet in subnets:
        retry(
            functools.partial(clients.ec2.delete_subnet, SubnetId=subnet["SubnetId"]),
            ("DependencyViolation",),
            "Subnet",
            seams,
            out,
            minutes=5,
        )
    retry(
        lambda: clients.ec2.delete_vpc(VpcId=vpc_id),
        ("DependencyViolation",),
        "Default VPC",
        seams,
        out,
        minutes=5,
    )
    did(todo, out, f"Deleted: default VPC {vpc['CidrBlock']}, its internet gateway and subnets.")


# 8. This Mac -----------------------------------------------------------------------


def remove_local(paths: Paths, seams: Seams, out: Any, todo: Todo, apply: bool) -> None:
    for account in KEYCHAIN_ACCOUNTS:
        if seams.keychain_has(account):
            note(todo, out, apply, f"To delete: Keychain item {sg.KEYCHAIN_SERVICE} / {account}.")
            if apply and seams.delete_keychain_item(account):
                did(todo, out, f"Deleted: Keychain item {sg.KEYCHAIN_SERVICE} / {account}.")
    files = [paths.state_dir / name for name in STATE_FILES]
    files += [paths.ssh_key, paths.ssh_key.with_name(paths.ssh_key.name + ".new")]
    for path in files:
        if path.exists():
            note(todo, out, apply, f"To delete: {paths.show(path)}.")
            if apply:
                path.unlink()
                did(todo, out, f"Deleted: {paths.show(path)}.")
    if apply and paths.state_dir.is_dir() and not any(paths.state_dir.iterdir()):
        paths.state_dir.rmdir()
        out.say(f"Deleted: the empty folder {paths.show(paths.state_dir)}.")
    present = seams.image_present()
    if present is None:
        out.say(f"Docker: not running here, so the local image {sg.IMAGE} was left alone.")
    elif present:
        note(todo, out, apply, f"To delete: local Docker image {sg.IMAGE}.")
        if apply and seams.remove_image():
            did(todo, out, f"Deleted: local Docker image {sg.IMAGE}.")


# Run -------------------------------------------------------------------------------


def run(
    clients: Any, seams: Seams, paths: Paths, out: Any, apply: bool, keep_instance: bool
) -> int:
    todo = Todo()
    world = discover(clients, out)
    steps: list[tuple[Callable[[], None], str]] = [
        (functools.partial(remove_agentcore, clients, seams, out, todo, apply), "AgentCore"),
        (functools.partial(remove_role, clients, out, todo, apply), "IAM"),
    ]
    for step, what in steps:
        try:
            step()
        except ClientError as error:
            if apply or not _code(error).startswith("AccessDenied"):
                raise
            out.say(f"{what}: these credentials cannot read it here; apply checks it.")
    remove_load_balancer(clients, world, seams, out, todo, apply)
    remove_spike_groups(clients, world, seams, out, todo, apply)
    remove_certificate(clients, world, seams, out, todo, apply)
    if keep_instance:
        remove_server_container(world, seams, out, todo, apply)
    else:
        remove_instance(clients, world, seams, out, todo, apply)
        remove_default_vpc(clients, world, seams, out, todo, apply)
        remove_local(paths, seams, out, todo, apply)
    if not apply:
        out.say(f"Teardown plan: {len(todo.items)} to delete.")
        return 0
    if keep_instance:
        out.say(
            f"Teardown complete: A5's resources are gone ({todo.done} actions); the instance "
            "and the rest of A1 to A4 remain."
        )
    else:
        out.say(f"Teardown complete: nothing the spike created is left ({todo.done} actions).")
    return 0


# Real seams ------------------------------------------------------------------------


def _security(*args: str) -> int:
    return subprocess.run(  # noqa: S603 - fixed program and arguments
        [sg.SECURITY, *args], capture_output=True, text=True, check=False
    ).returncode


def keychain_has(account: str) -> bool:
    return _security("find-generic-password", "-s", sg.KEYCHAIN_SERVICE, "-a", account) == 0


def delete_keychain_item(account: str) -> bool:
    return _security("delete-generic-password", "-s", sg.KEYCHAIN_SERVICE, "-a", account) == 0


def _docker(*args: str) -> int | None:
    try:
        return subprocess.run(  # noqa: S603 - docker from PATH, fixed arguments
            [DOCKER, *args], capture_output=True, text=True, check=False, timeout=60
        ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return None


def image_present() -> bool | None:
    if _docker("info") != 0:
        return None
    return _docker("image", "inspect", sg.IMAGE) == 0


def remove_image() -> bool:
    return _docker("image", "rm", sg.IMAGE) == 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Spike A, A6: remove what A1 to A5 created, in dependency order."
    )
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument(
        "--keep-instance",
        action="store_true",
        help="remove only A5's resources; keep the instance and the rest of A1 to A4",
    )
    parser.add_argument("--key", type=Path, default=Path.home() / ".ssh" / "rancher-spike.pem")
    args = parser.parse_args(argv)
    out = sg.Out()
    clients = sg.Clients.from_session(boto3.Session(region_name=sg.REGION))
    key = args.key.expanduser()
    seams = Seams(
        run_on_instance=sg.ssh_runner(key, out),
        keychain_has=keychain_has,
        delete_keychain_item=delete_keychain_item,
        image_present=image_present,
        remove_image=remove_image,
    )
    paths = Paths(home=Path.home(), state_dir=sg.STATE_DIR, ssh_key=key)
    try:
        return run(clients, seams, paths, out, args.mode == "apply", args.keep_instance)
    except (TeardownError, sg.SetupError) as error:
        out.say(f"teardown: {error}. Fix the cause and run the same command again.")
        return 1
    except (ClientError, BotoCoreError) as error:
        out.say(f"teardown: an AWS call failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
