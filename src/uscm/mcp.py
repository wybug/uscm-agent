"""MCP server (stdio) exposing the decision core to coding agents.

Optional extra: ``pip install 'uscm-agent[mcp]'``. Tools:

- ``uscm_status``       workspace summary (repos, features, flags, calibration)
- ``uscm_calibration``  active coefficients, tau, Phi bands, self-checks
- ``uscm_check``        single-merge R1' verdict (repo name + merge sha)
- ``uscm_advise``       per-feature report or top-K scatter-risk ranking

The server runs in the workspace directory it was started from; all outputs
are deterministic JSON strings produced by the same core the CLI uses.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import state as st_mod


def _st(ws: Path):
    st = st_mod.load_state(ws)
    if st is None:
        raise RuntimeError("no workspace state in server cwd: run `uscm init`")
    return st


def serve() -> None:
    try:
        try:
            from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
        except ImportError:
            from mcp.server.fastmcp import FastMCP as Server       # mcp 1.x
    except ImportError:
        raise SystemExit("the 'mcp' package is not installed; "
                         "pip install 'uscm-agent[mcp]'")

    ws = Path.cwd()
    mcp = Server("uscm-agent")

    @mcp.tool()
    def uscm_status() -> str:
        """Workspace summary: repos/schemes, feature count, flags, calibration mode."""
        st = _st(ws)
        calib = st_mod.active_calibration(st)
        return json.dumps({
            "repos": {n: {"scheme": r["scheme"]["type"], "head": r["head"]}
                      for n, r in st["repos"].items()},
            "features": len(st["features"]), "stats": st["stats"],
            "calibration_mode": calib["mode"], "tau": calib["tau"],
        }, ensure_ascii=False)

    @mcp.tool()
    def uscm_calibration() -> str:
        """Active coefficients, tau (with provenance), Phi bands, self-checks."""
        st = _st(ws)
        return json.dumps({"active": st_mod.active_calibration(st),
                           "stored": st.get("calibration")}, ensure_ascii=False)

    @mcp.tool()
    def uscm_check(repo: str, sha: str) -> str:
        """R1' verdict for one merge (read-only; pre-event information only).

        Use before merging or reviewing a change: returns FLAG/PASS/OK with
        P(scatter), tau, new placement units, and the guardrail comment text.
        """
        from .guard import check, comment_text
        v = check(ws, repo, sha)
        if v["verdict"] == "FLAG":
            v["comment"] = comment_text(v)
        return json.dumps(v, ensure_ascii=False)

    @mcp.tool()
    def uscm_advise(story: str = "", top: int = 10) -> str:
        """Per-feature decision report (story=key) or top-K scatter-risk ranking."""
        st = _st(ws)
        calib = st_mod.active_calibration(st)
        from .advise import advise_feature, rank_features
        if story:
            rep = advise_feature(st, calib, story)
            if rep is None:
                return json.dumps({"error": f"unknown feature {story}"})
            return json.dumps(rep, ensure_ascii=False)
        return json.dumps(rank_features(st, calib, top=top), ensure_ascii=False)

    mcp.run()
