#!/usr/bin/env python3
"""Spike A, A4 and A5: talk to rancher-ai-mcp as an MCP client would.

By default it starts tools/spikes/spike-a/rancher-mcp.sh (extra arguments after `--` go to it,
for example `-- --read-only`): A4, the server on this Mac. With --gateway it starts AWS's
SigV4 proxy, mcp-proxy-for-aws-cli 1.8.0, for the AgentCore Gateway that setup_gateway.py
saved in ~/.rancher-spike/gateway.json: A5, the same server reached through the gateway and
its private endpoint. The proxy signs with your current AWS credentials (AWS_PROFILE). Both
speak MCP's stdio transport: one JSON-RPC message per line. Standard library only.

    python3 tools/spikes/spike-a/mcp_probe.py [--gateway] tools [NAME ...]
    python3 tools/spikes/spike-a/mcp_probe.py [--gateway] call TOOL '{"json": "arguments"}'

Through the gateway, tool names carry the target's prefix, for example
`rancher___listKubernetesResources`.

`tools` lists every tool with its read-only hint, and prints the input schema of
each NAME given. `call` calls one tool and prints its result. The server's log goes
to a file next to this script only when something fails, with anything shaped like
a Rancher token redacted. This script never sees the token itself.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
LAUNCHER = HERE / "rancher-mcp.sh"
GATEWAY_STATE = Path.home() / ".rancher-spike" / "gateway.json"
PROXY = "mcp-proxy-for-aws-cli@1.8.0"
PROTOCOL = "2025-06-18"
TOKEN_SHAPE = re.compile(r"token-[a-z0-9]+:[A-Za-z0-9]+")
# Detailed gateway errors may quote the target URL or an ARN; hide the domain and account.
PRIVATE_SHAPES = (
    (re.compile(r"mcp-spike\.[A-Za-z0-9.-]+"), "mcp-spike.<domain>"),
    (re.compile(r"\b\d{12}\b"), "<account>"),
)


def scrub(text: str) -> str:
    text = TOKEN_SHAPE.sub("token-[redacted]", text)
    for shape, label in PRIVATE_SHAPES:
        text = shape.sub(label, text)
    return text


TIMEOUT_SECONDS = 120.0


def gateway_command() -> list[str]:
    """The SigV4 proxy for the gateway that setup_gateway.py saved."""
    state = json.loads(GATEWAY_STATE.read_text())
    return [
        "uvx",
        PROXY,
        str(state["gatewayUrl"]),
        "--service",
        "bedrock-agentcore",
        "--region",
        str(state.get("region", "us-east-1")),
        "--disable-telemetry",
    ]


def summarize(content: list[dict[str, Any]]) -> str:
    """One line: how many resources a list call returned, and their kind and names."""
    text = " ".join(str(item.get("text", "")) for item in content)
    try:
        items = json.loads(text).get("llm")
    except (ValueError, AttributeError):
        return "summary: " + scrub(text)[:400]
    if not isinstance(items, list):
        return "summary: one object"
    kinds = sorted({str(i.get("kind")) for i in items if isinstance(i, dict)})
    names = [str(i.get("metadata", {}).get("name")) for i in items if isinstance(i, dict)]
    return f"summary: {len(items)} {'/'.join(kinds)}: {', '.join(names[:6])}"


class Server:
    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(  # noqa: S603 - the launcher here, or the pinned proxy
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if not (self.process.stdin and self.process.stdout and self.process.stderr):
            raise RuntimeError("the launcher started without its pipes")
        self.stdin, self.stdout, self.stderr = (
            self.process.stdin,
            self.process.stdout,
            self.process.stderr,
        )
        self.log: list[str] = []
        threading.Thread(target=self._drain, daemon=True).start()
        self.next_id = 0

    def _drain(self) -> None:
        for line in self.stderr:
            self.log.append(TOKEN_SHAPE.sub("token-[redacted]", line.rstrip()))

    def send(self, message: dict[str, Any]) -> None:
        self.stdin.write(json.dumps(message) + "\n")
        self.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params})
        result: dict[str, Any] = {}
        reader = threading.Thread(target=self._read_reply, args=(self.next_id, result), daemon=True)
        reader.start()
        reader.join(TIMEOUT_SECONDS)
        if "reply" not in result:
            raise RuntimeError(f"no reply to {method} within {TIMEOUT_SECONDS:.0f} s")
        reply: dict[str, Any] = result["reply"]
        if "error" in reply:
            raise RuntimeError(f"{method} failed: {json.dumps(reply['error'])[:800]}")
        return dict(reply["result"])

    def _read_reply(self, wanted: int, result: dict[str, Any]) -> None:
        for line in self.stdout:
            line = line.strip()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == wanted:
                result["reply"] = message
                return

    def start(self) -> dict[str, Any]:
        info = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "spike-a-probe", "version": "0.1"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return info

    def tools(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = self.request("tools/list", {"cursor": cursor} if cursor else {})
            found.extend(page.get("tools", []))
            cursor = page.get("nextCursor")
            if not cursor:
                return found

    def stop(self) -> None:
        self.stdin.close()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.terminate()


def main(argv: list[str]) -> int:
    extra: list[str] = []
    if "--" in argv:
        extra = argv[argv.index("--") + 1 :]
        argv = argv[: argv.index("--")]
    via_gateway = bool(argv) and argv[0] == "--gateway"
    if via_gateway:
        argv = argv[1:]
    if not argv or argv[0] not in ("tools", "call"):
        print(__doc__, file=sys.stderr)
        return 2
    if via_gateway and not GATEWAY_STATE.exists():
        print("mcp_probe: run setup_gateway.py apply first", file=sys.stderr)
        return 2
    server = Server(gateway_command() if via_gateway else [str(LAUNCHER), *extra])
    try:
        info = server.start()
        name = info.get("serverInfo", {})
        version = info.get("protocolVersion")
        print(f"Server: {name.get('name')} {name.get('version')}, protocol {version}")
        if argv[0] == "tools":
            tools = server.tools()
            reads = [t for t in tools if (t.get("annotations") or {}).get("readOnlyHint")]
            print(f"Tools: {len(tools)} ({len(reads)} marked read-only)")
            for tool in sorted(tools, key=lambda t: str(t["name"])):
                hint = "read" if tool in reads else "WRITE"
                print(f"  {hint:5} {tool['name']}")
            for wanted in argv[1:]:
                schema = next((t.get("inputSchema") for t in tools if t["name"] == wanted), None)
                print(f"{wanted} input schema: {json.dumps(schema, indent=1)}")
        else:
            arguments = json.loads(argv[2]) if len(argv) > 2 else {}
            names = [str(t["name"]) for t in server.tools()]
            if argv[1] not in names:
                base = argv[1].split("___")[-1]
                matches = [n for n in names if n.split("___")[-1] == base]
                if len(matches) != 1:
                    raise RuntimeError(f"no single tool named like {argv[1]}")
                print(f"Tool: {argv[1]} is listed here as {matches[0]}")
                argv[1] = matches[0]
            result = server.request("tools/call", {"name": argv[1], "arguments": arguments})
            print(f"isError: {bool(result.get('isError'))}")
            print(summarize(result.get("content", [])))
            for item in result.get("content", []):
                text = str(item.get("text", item))
                print(scrub(text))
        return 0
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"mcp_probe: {scrub(str(error))}", file=sys.stderr)
        print("Server log (last 15 lines):", file=sys.stderr)
        for line in server.log[-15:]:
            print(f"  {scrub(line)[:300]}", file=sys.stderr)
        return 1
    finally:
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
