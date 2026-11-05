"""The stack's outbound controls, read from the template itself (DR-025 section 19, fix 15).

Why a test over the template: the secret references, the one-task rule and the absence of new resources are
controls a later edit could undo without a word, and cfn-lint would still pass.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "aws" / "candidate-line-stack.yaml"
OUTBOUND_SECRETS = ("INTAKE_SIGNING_KEY", "OUTBOUND_ALLOWED_NUMBERS", "TWILIO_LINE_NUMBER")
# The resources the stack held before card 08; DR-025 adds none.
RESOURCES = {
    "Vpc",
    "InternetGateway",
    "VpcGatewayAttachment",
    "SubnetA",
    "SubnetB",
    "RouteTable",
    "DefaultRoute",
    "SubnetARoute",
    "SubnetBRoute",
    "AlbSecurityGroup",
    "TaskSecurityGroup",
    "EfsSecurityGroup",
    "FileSystem",
    "MountTargetA",
    "MountTargetB",
    "VarAccessPoint",
    "LogGroup",
    "HandOffTopic",
    "HandOffSubscription",
    "OperatorIdentity",
    "ExecutionRole",
    "TaskRole",
    "Cluster",
    "TaskDefinition",
    "Service",
    "LoadBalancer",
    "TargetGroup",
    "HttpListener",
    "WebAcl",
    "WebSocketOriginRequestPolicy",
    "Distribution",
    "BudgetActionRole",
    "DenyAllPolicy",
    "SpendBudget",
    "StopAction",
}


class _CfnLoader(yaml.SafeLoader):
    """Reads !Ref, !Sub, !GetAtt and the rest as {tag: value}, so the template loads without CloudFormation."""


def _tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> dict[str, Any]:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)  # type: ignore[arg-type]
    return {suffix: value}


_CfnLoader.add_multi_constructor("!", _tag)


def _template() -> dict[str, Any]:
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_CfnLoader)


def _container() -> dict[str, Any]:
    [line] = _template()["Resources"]["TaskDefinition"]["Properties"]["ContainerDefinitions"]
    return line


def test_the_three_outbound_secrets_are_secret_references_and_never_environment_values() -> None:
    line = _container()
    secrets = {s["Name"]: s["ValueFrom"]["Sub"] for s in line["Secrets"]}
    for name in OUTBOUND_SECRETS:
        assert secrets[name].endswith(f":secret:candidate-line/{name}"), name
        assert secrets[name].startswith("arn:aws:secretsmanager:${AWS::Region}:${AWS::AccountId}:")
    environment = {e["Name"] for e in line["Environment"]}
    assert not environment & set(OUTBOUND_SECRETS)
    # Nor anywhere else a value could slip in: no plain value in the task definition names one of them.
    plain = repr(line["Environment"]) + repr(_template()["Parameters"])
    assert not any(name in plain for name in OUTBOUND_SECRETS)


def test_the_execution_role_reads_exactly_the_secrets_the_task_references() -> None:
    role = _template()["Resources"]["ExecutionRole"]["Properties"]["Policies"]
    policy = next(p for p in role if p["PolicyName"] == "read-the-line-secrets")
    [statement] = policy["PolicyDocument"]["Statement"]
    assert statement["Action"] == "secretsmanager:GetSecretValue" and statement["Effect"] == "Allow"
    readable = set()
    for resource in statement["Resource"]:
        m = re.fullmatch(
            r"arn:aws:secretsmanager:\$\{AWS::Region\}:\$\{AWS::AccountId\}:secret:candidate-line/"
            r"([A-Z_]+)-\?\?\?\?\?\?",
            resource["Sub"],
        )
        assert m, resource
        readable.add(m.group(1))
    referenced = {s["Name"] for s in _container()["Secrets"]}
    assert readable == referenced and set(OUTBOUND_SECRETS) <= readable


def test_the_new_parameters_reach_the_task_with_their_defaults() -> None:
    params = _template()["Parameters"]
    assert params["OutboundEnabled"]["Default"] == "0" and params["OutboundEnabled"]["AllowedValues"] == [
        "0",
        "1",
    ]
    assert params["MaxOutboundPerDay"]["Default"] == 20 and params["MaxOutboundPerDay"]["MinValue"] == 1
    assert params["MaxOutboundCallSeconds"]["Default"] == 480
    window = params["CallWindow"]
    assert window["Default"] == "09:00-20:00 Mon-Sat"
    assert re.fullmatch(window["AllowedPattern"], window["Default"])
    for sunday in ("09:00-20:00 Mon-Sun", "09:00-20:00 Sun-Sat"):
        assert not re.fullmatch(window["AllowedPattern"], sunday)
    environment = {e["Name"]: e["Value"] for e in _container()["Environment"]}
    assert environment["OUTBOUND_ENABLED"] == {"Ref": "OutboundEnabled"}
    assert environment["MAX_OUTBOUND_PER_DAY"] == {"Ref": "MaxOutboundPerDay"}
    assert environment["CALL_WINDOW"] == {"Ref": "CallWindow"}
    assert environment["MAX_OUTBOUND_CALL_SECONDS"] == {"Ref": "MaxOutboundCallSeconds"}
    assert environment["CONTACTS_PATH"] == "/app/var/contacts.json"  # on the encrypted volume


def test_one_task_and_never_two_and_no_new_resource() -> None:
    template = _template()
    service = template["Resources"]["Service"]["Properties"]
    assert service["DesiredCount"] == 1 and service["DeploymentConfiguration"]["MaximumPercent"] == 100
    assert set(template["Resources"]) == RESOURCES
    assert template["Resources"]["FileSystem"]["Properties"]["Encrypted"] is True


def test_the_template_holds_no_account_id_and_no_phone_number() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"(?<![0-9])[0-9]{12}(?![0-9])", text)
    assert not re.search(r"\+1[2-9][0-9]{2}[2-9][0-9]{6}", text)
