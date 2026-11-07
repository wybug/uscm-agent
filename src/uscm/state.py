"""Workspace state and configuration.

A *workspace* is the current directory; everything lives under ``.uscm/``:

- ``state.json`` : repos (path + module scheme + head), feature table,
  processed-merge registry, R1' flags, active calibration
- ``reports/``   : monthly reports written by ``uscm report``

Optional ``uscm.toml`` alongside the workspace root:

    since      = "2024-01-01"
    tau        = 0.35
    mainline   = true            # count first-parent mainline merges only
    unit_style = "module"        # "module" | "pkg" (business-package units for
                                 # DDD-layered monorepos)
    repos      = ["path/to/repo", "glob*/pattern"]

    [[feature]]
    regex = "--story=(\\d+)"
    tag   = "S{0}"

The feature table is updated only by applying merges in global date order
(``apply_merge``); every R1' evaluation reads the table strictly *before*
applying the merge being judged, so no evaluation ever sees future data.
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

from . import model

STATE_VERSION = 1
DEFAULT_TAU_PRIOR = 0.35


# ---------------------------------------------------------------- config ---

def _default_config() -> dict:
    return {"since": None, "tau": None, "repos": [], "mainline": True,
            "unit_style": "module", "skip_segments": None,
            "feature_patterns": None}


def load_config(ws: Path) -> dict:
    cfg = _default_config()
    f = ws / "uscm.toml"
    if not f.exists():
        return cfg
    try:
        import tomllib
        data = tomllib.loads(f.read_text())
    except ModuleNotFoundError:  # pragma: no cover - py>=3.11 has tomllib
        raise SystemExit("uscm.toml found but tomllib unavailable (need Python >= 3.11)")
    cfg["since"] = data.get("since")
    cfg["tau"] = data.get("tau")
    cfg["mainline"] = data.get("mainline", True)
    cfg["unit_style"] = data.get("unit_style", "module")
    cfg["skip_segments"] = data.get("skip_segments")
    cfg["repos"] = data.get("repos", [])
    feats = data.get("feature", [])
    if feats:
        cfg["feature_patterns"] = [(f["regex"], f["tag"]) for f in feats]
    return cfg


def resolve_repos(patterns: list[str]) -> dict[str, Path]:
    """Expand repo paths/globs -> {name: path}; name = dir basename."""
    out: dict[str, Path] = {}
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            hits = sorted(glob.glob(os.path.expanduser(pat)))
        else:
            hits = [os.path.expanduser(pat)]
        for h in hits:
            p = Path(h).resolve()
            if (p / ".git").exists():
                out[p.name] = p
    return out


# ----------------------------------------------------------------- state ---

def state_path(ws: Path) -> Path:
    return ws / ".uscm" / "state.json"


def load_state(ws: Path) -> dict | None:
    f = state_path(ws)
    if not f.exists():
        return None
    return json.loads(f.read_text())


def save_state(ws: Path, st: dict) -> None:
    f = state_path(ws)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, ensure_ascii=False))


def new_state(ws: Path, cfg: dict, repos: dict[str, Path]) -> dict:
    return {
        "version": STATE_VERSION,
        "workspace": str(ws),
        "config": {"since": cfg.get("since"), "tau": cfg.get("tau"),
                   "mainline": cfg.get("mainline", True),
                   "feature_patterns": cfg.get("feature_patterns")},
        "repos": {name: {"path": str(p), "scheme": None, "head": None}
                  for name, p in repos.items()},
        "features": {},
        "processed": {name: [] for name in repos},
        "flags": [],
        "stats": {"merges": 0, "flags": 0},
        "calibration": None,
    }


# ------------------------------------------------------------ calibration --

def active_calibration(st: dict | None) -> dict:
    """Coefficient set + tau currently in force (local fit or pooled prior)."""
    calib = (st or {}).get("calibration") or {}
    if calib.get("mode") == "local" and calib.get("coef"):
        return {"mode": "local", "coef": calib["coef"], "tau": calib["tau"],
                "tau_source": "local-base-rate", "fitted_at": calib.get("fitted_at")}
    prior = model.load_prior()
    tau = ((st or {}).get("config") or {}).get("tau")
    if tau is None:
        tau = prior.get("tau_prior_default", DEFAULT_TAU_PRIOR)
    return {"mode": "prior", "coef": model.prior_coef(prior), "tau": tau,
            "tau_source": "prior-placeholder", "fitted_at": None}


# ------------------------------------------------------- feature table ops --

def feature_stats(st: dict, key: str) -> dict | None:
    f = st["features"].get(key)
    if not f:
        return None
    return {"nMR": f["nMR"], "ka": len(f.get("authors", {})) or 1,
            "ga": model.ga_of(f.get("authors", {})),
            "units": sorted(f.get("units", {})),
            "phi": len(f.get("units", {}))}


def update_feature(st: dict, key: str, repo: str, units: set, author, n_files: int,
                   date: str) -> None:
    f = st["features"].setdefault(
        key, {"units": {}, "nMR": 0, "authors": {}, "repos": {},
              "sizes": [], "first": date, "last": date})
    for u in units:
        f["units"][u] = f["units"].get(u, 0) + 1
    f["nMR"] += 1
    f["repos"][repo] = f["repos"].get(repo, 0) + 1
    f["sizes"].append(int(n_files))
    if author:
        f["authors"][author] = f["authors"].get(author, 0) + 1
    if date and date < f["first"]:
        f["first"] = date
    if date and date > f["last"]:
        f["last"] = date
