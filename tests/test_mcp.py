"""MCP server smoke test: stdio JSON-RPC handshake and tool listing."""
import json
import subprocess
import sys

import pytest

pytest.importorskip("mcp")

from conftest import make_merge            # noqa: E402
from uscm import state as st_mod           # noqa: E402
from uscm.guard import init_replay         # noqa: E402


def _read_until_id(proc, want_id, max_lines=50):
    for _ in range(max_lines):
        line = proc.stdout.readline()
        if not line:
            raise AssertionError("server closed stdout")
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("id") == want_id:
            return obj
    raise AssertionError(f"no response with id={want_id}")


def test_mcp_handshake_and_tools(ws, tiny_repo):
    make_merge(tiny_repo, 1, ["core/src/main/java/com/x/core/A.java"])
    cfg = st_mod.load_config(ws)
    init_replay(ws, cfg, [str(tiny_repo)], None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "uscm.cli", "mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, cwd=ws)

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "pytest", "version": "0"}}})
        init = _read_until_id(proc, 1)
        assert "uscm-agent" in json.dumps(init)

        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = _read_until_id(proc, 2)
        names = {t["name"] for t in tools["result"]["tools"]}
        assert {"uscm_status", "uscm_check", "uscm_advise",
                "uscm_calibration"} <= names

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "uscm_status", "arguments": {}}})
        status = _read_until_id(proc, 3)
        payload = json.loads(status["result"]["content"][0]["text"])
        assert payload["features"] == 1
    finally:
        proc.terminate()
        proc.wait(timeout=10)
