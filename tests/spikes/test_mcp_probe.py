"""Tests for tools/spikes/spike-a/mcp_probe.py, against a fake MCP server on stdio.

The fake answers MCP's stdio transport (one JSON-RPC message per line): two pages of
tools, a list call, a call whose text holds values the probe must hide, an error, and a
call it never answers. Every value in it is synthetic.
"""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
SECRET = "token-abcde:SECRETvalue1"  # noqa: S105 - a synthetic value the probe must hide


def _load() -> ModuleType:
    path = REPO / "tools/spikes/spike-a/mcp_probe.py"
    spec = importlib.util.spec_from_file_location("mcp_probe", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = _load()

FAKE_SERVER = """#!{python}
import json
import sys

SECRET = "{secret}"
PAGE_1 = [
    {{"name": "rancher___listKubernetesResources",
      "inputSchema": {{"type": "object", "properties": {{"kind": {{"type": "string"}}}}}}}},
    {{"name": "rancher___echo", "inputSchema": {{"type": "object"}},
      "annotations": {{"readOnlyHint": True}}}},
]
PAGE_2 = [
    {{"name": "rancher___fail", "inputSchema": {{"type": "object"}}}},
    {{"name": "rancher___hang", "inputSchema": {{"type": "object"}}}},
]
print("starting with " + SECRET + " for 123456789012", file=sys.stderr, flush=True)
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message.get("method")
    reply = {{"jsonrpc": "2.0", "id": message["id"]}}
    if method == "initialize":
        reply["result"] = {{
            "protocolVersion": "2025-06-18",
            "serverInfo": {{"name": "fake", "version": "1"}},
            "capabilities": {{}},
        }}
    elif method == "tools/list":
        if message.get("params", {{}}).get("cursor") == "page-2":
            reply["result"] = {{"tools": PAGE_2}}
        else:
            reply["result"] = {{"tools": PAGE_1, "nextCursor": "page-2"}}
    elif method == "tools/call":
        name = message["params"]["name"]
        if name == "rancher___listKubernetesResources":
            names = ("default", "kube-system")
            items = [{{"kind": "Namespace", "metadata": {{"name": n}}}} for n in names]
            text = json.dumps({{"llm": items}})
            reply["result"] = {{"content": [{{"type": "text", "text": text}}], "isError": False}}
        elif name == "rancher___echo":
            text = "seen https://mcp-spike.example.org/mcp from 123456789012 with " + SECRET
            reply["result"] = {{"content": [{{"type": "text", "text": text}}], "isError": True}}
        elif name == "rancher___hang":
            continue
        else:
            reply["error"] = {{"code": -32000, "message": "boom for " + SECRET}}
    print(json.dumps(reply), flush=True)
"""


@pytest.fixture
def fake_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the probe's launcher at the fake server."""
    script = tmp_path / "fake-mcp-server"
    script.write_text(FAKE_SERVER.format(python=sys.executable, secret=SECRET))
    script.chmod(0o755)
    monkeypatch.setattr(probe, "LAUNCHER", script)
    return script


def test_tools_reads_every_page_and_prints_a_schema(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["tools", "rancher___listKubernetesResources"]) == 0

    out = capsys.readouterr().out
    assert "Server: fake 1, protocol 2025-06-18" in out
    assert "Tools: 4 (1 marked read-only)" in out
    assert "  read  rancher___echo" in out
    assert "  WRITE rancher___hang" in out
    assert '"kind"' in out


def test_extra_arguments_after_the_separator_go_to_the_launcher(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["tools", "--", "--read-only"]) == 0
    assert "Tools: 4" in capsys.readouterr().out


def test_call_finds_a_tool_by_its_name_without_the_target_prefix(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["call", "listKubernetesResources", '{"kind": "Namespace"}']) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        "Tool: listKubernetesResources is listed here as rancher___listKubernetesResources"
    )
    assert lines[2] == "isError: False"
    assert lines[3] == "summary: 2 Namespace: default, kube-system"


def test_call_hides_tokens_hostnames_and_accounts(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["call", "rancher___echo"]) == 0

    out = capsys.readouterr().out
    assert "isError: True" in out
    for private in ("SECRETvalue1", "123456789012", "example.org"):
        assert private not in out
    assert "mcp-spike.<domain>" in out
    assert "<account>" in out
    assert "token-[redacted]" in out


def test_a_failing_call_prints_a_scrubbed_error(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["call", "rancher___fail"]) == 1

    err = capsys.readouterr().err
    assert err.startswith("mcp_probe: tools/call failed:")
    assert "token-[redacted]" in err
    assert "Server log (last 15 lines):" in err
    assert "SECRETvalue1" not in err
    assert "123456789012" not in err


def test_a_call_with_no_reply_times_out(
    fake_server: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(probe, "TIMEOUT_SECONDS", 0.5)

    assert probe.main(["call", "rancher___hang"]) == 1
    assert "no reply to tools/call" in capsys.readouterr().err


def test_a_name_that_matches_no_tool_is_an_error(
    fake_server: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main(["call", "nothing"]) == 1
    assert "no single tool named like nothing" in capsys.readouterr().err


def test_usage_and_the_gateway_before_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe.main([]) == 2
    assert probe.main(["list"]) == 2
    monkeypatch.setattr(probe, "GATEWAY_STATE", tmp_path / "missing.json")
    assert probe.main(["--gateway", "tools"]) == 2
    assert "run setup_gateway.py apply first" in capsys.readouterr().err


def test_the_gateway_command_signs_through_the_pinned_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "https://gw-1.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
    state = tmp_path / "gateway.json"
    state.write_text(json.dumps({"gatewayUrl": url, "region": "us-east-1"}))
    monkeypatch.setattr(probe, "GATEWAY_STATE", state)

    assert probe.gateway_command() == [
        "uvx",
        "mcp-proxy-for-aws-cli@1.8.0",
        url,
        "--service",
        "bedrock-agentcore",
        "--region",
        "us-east-1",
        "--disable-telemetry",
    ]


@pytest.mark.parametrize(
    ("content", "line"),
    [
        (
            [{"text": json.dumps({"llm": [{"kind": "Pod", "metadata": {"name": "web-1"}}]})}],
            "summary: 1 Pod: web-1",
        ),
        ([{"text": json.dumps({"other": 1})}], "summary: one object"),
        ([{"text": "plain words"}], "summary: plain words"),
        ([{"text": "[1, 2]"}], "summary: [1, 2]"),
    ],
)
def test_summarize(content: list[dict[str, str]], line: str) -> None:
    assert probe.summarize(content) == line


def test_scrub_hides_every_private_shape() -> None:
    text = f"failed https://mcp-spike.example.co.uk/mcp for 123456789012 with {SECRET}"
    assert probe.scrub(text) == (
        "failed https://mcp-spike.<domain>/mcp for <account> with token-[redacted]"
    )
