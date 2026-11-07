"""Two-layer calibration (USCM-CC paper, Section 1.4 / model v2 Section 3).

Layer 1 (public prior): the pooled regime law shipped in
``uscm/priors/regime_pooled.json`` - usable cold, from git history alone.

Layer 2 (local, monthly): refit the logistic law on this system's recent
feature units; tau becomes the local regime base rate; Phi budgets become
per-nMR-band P90 quantiles. Three self-checks run alongside:

1. direction  - share of repositories where median Phi is non-decreasing
                across nMR bands
2. drift      - scatter-regime share, recent 6 months vs prior 6 months
3. precision  - share of flagged features that ended heavily scattered
                (N1 >= 6 or Phi in the top tercile), vs unflagged features
"""
from __future__ import annotations

import datetime as dt

import numpy as np

from . import state as st_mod
from .model import (auc, band_of, coef_se, feats, fit_logit, ga_of,
                    phi_band_table)

MIN_UNITS = 40
MIN_CLASS = 8


def _scheme_type(st: dict, repo: str) -> str:
    sch = st["repos"].get(repo, {}).get("scheme") or {}
    return sch.get("type", "flat2")


def feature_is_scattered(st: dict, f: dict) -> int:
    """Label per the paper: N1 >= 3 modules; front-end: >= 2 distinct pages."""
    n_units = len(f.get("units", {}))
    types = [_scheme_type(st, r) for r in f.get("repos", {})]
    if types and all(t == "front" for t in types):
        return 1 if n_units >= 2 else 0
    return 1 if n_units >= 3 else 0


def gather_rows(st: dict) -> list[dict]:
    rows = []
    for key, f in st["features"].items():
        if f["nMR"] < 2:
            continue
        rows.append({"key": key, "nMR": f["nMR"], "Phi": len(f["units"]),
                     "KA": len(f.get("authors", {})) or 1,
                     "GA": ga_of(f.get("authors", {})), "last": f["last"],
                     "repos": sorted(f.get("repos", {})),
                     "scatter": feature_is_scattered(st, f)})
    return rows


def _cv_auc(rows: list[dict], folds: int = 5, seed: int = 7) -> float | None:
    X = np.array([feats(r["nMR"], r["KA"], r["GA"]) for r in rows])
    y = np.array([r["scatter"] for r in rows], float)
    rng = np.random.default_rng(seed)
    idx = rng.permutation(len(y))
    parts = np.array_split(idx, folds)
    scores = []
    for te in parts:
        tr = np.setdiff1d(idx, te)
        w = fit_logit(X[tr], y[tr])
        a = auc(y[te], X[te] @ w)
        if a is not None:
            scores.append(a)
    return round(float(np.mean(scores)), 3) if scores else None


def self_checks(st: dict, rows: list[dict]) -> dict:
    # 1. direction: per-repo median Phi non-decreasing across nMR bands
    per_repo: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        for repo in r["repos"]:
            per_repo.setdefault(repo, {}).setdefault(band_of(r["nMR"]), []) \
                     .append(r["Phi"])
    order = [band_of(lo) for lo, _ in [(1, 1), (2, 3), (4, 8), (9, None)]]
    checked = passed = 0
    for repo, bands in per_repo.items():
        seq = [float(np.median(bands[b])) for b in order
               if b in bands and len(bands[b]) >= 3]
        if len(seq) < 2:
            continue
        checked += 1
        if all(x <= y + 1e-9 for x, y in zip(seq, seq[1:])):
            passed += 1
    direction = {"share": round(passed / checked, 2) if checked else None,
                 "repos_checked": checked}

    # 2. regime-share drift: last 6m vs prior 6m (relative to newest activity)
    dates = [r["last"] for r in rows if r["last"]]
    if dates:
        newest = max(dt.date.fromisoformat(d[:10]) for d in dates)
        r6 = newest - dt.timedelta(days=183)
        p6 = newest - dt.timedelta(days=365)
        rec = [r for r in rows if dt.date.fromisoformat(r["last"][:10]) > r6]
        pri = [r for r in rows
               if p6 < dt.date.fromisoformat(r["last"][:10]) <= r6]
        drift = {"recent_share": round(np.mean([r["scatter"] for r in rec]), 3)
                 if rec else None,
                 "prior_share": round(np.mean([r["scatter"] for r in pri]), 3)
                 if pri else None,
                 "n_recent": len(rec), "n_prior": len(pri)}
    else:
        drift = {"recent_share": None, "prior_share": None,
                 "n_recent": 0, "n_prior": 0}

    # 3. alarm precision: flagged features ending heavily scattered
    flagged = {f["story"] for f in st.get("flags", [])}
    phis = sorted(r["Phi"] for r in rows)
    q67 = float(np.percentile(phis, 67)) if phis else None

    def heavy(key: str) -> bool | None:
        f = st["features"].get(key)
        if not f:
            return None
        n1 = len(f["units"])
        return n1 >= 6 or (q67 is not None and len(f["units"]) >= q67)

    fl = [heavy(k) for k in flagged]
    fl = [x for x in fl if x is not None]
    un = [heavy(r["key"]) for r in rows if r["key"] not in flagged]
    un = [x for x in un if x is not None]
    precision = {
        "flagged_heavy_share": round(float(np.mean(fl)), 3) if fl else None,
        "unflagged_heavy_share": round(float(np.mean(un)), 3) if un else None,
        "n_flagged": len(fl), "n_unflagged": len(un),
    }
    if precision["flagged_heavy_share"] and precision["unflagged_heavy_share"]:
        precision["lift"] = round(precision["flagged_heavy_share"]
                                  / precision["unflagged_heavy_share"], 2)
    return {"direction": direction, "regime_drift": drift,
            "alarm_precision": precision}


def _degeneracy_warnings(rows: list[dict], unit_style: str) -> list[str]:
    """Label-degeneracy check: a scatter base rate near 1 means the chosen
    placement unit is crossed normatively (e.g. modules are architecture
    layers), and the label carries no information."""
    out = []
    if rows:
        base = float(np.mean([r["scatter"] for r in rows]))
        if base >= 0.9 and unit_style != "pkg":
            out.append(
                f"scatter label degenerate (base rate {base:.2f} >= 0.90): "
                f"units look like normative structure (architecture layers?); "
                f"consider unit_style = 'pkg' (business-package units)")
        elif base <= 0.05:
            out.append(f"scatter base rate {base:.2f}: almost no positives - "
                       f"guardrail will never fire; check unit granularity")
    return out


def calibrate(ws, min_units: int = MIN_UNITS) -> dict:
    st = st_mod.load_state(ws)
    if st is None:
        raise SystemExit("no workspace state: run `uscm init` first")
    rows = gather_rows(st)
    unit_style = (st.get("config") or {}).get("unit_style", "module")
    warnings = _degeneracy_warnings(rows, unit_style)
    if len(rows) < min_units:
        calib = st_mod.active_calibration(st)
        result = {"mode": "prior", "coef": calib["coef"], "tau": calib["tau"],
                  "tau_source": "prior-placeholder", "n_units": len(rows),
                  "note": f"only {len(rows)} feature units (< {min_units}): "
                          f"keeping pooled prior; thresholds are placeholders"}
        if warnings:
            result["warnings"] = warnings
        st["calibration"] = {**result, "phi_bands": phi_band_table(rows),
                             "self_checks": self_checks(st, rows),
                             "fitted_at": dt.date.today().isoformat()}
        st_mod.save_state(ws, st)
        return result

    X = np.array([feats(r["nMR"], r["KA"], r["GA"]) for r in rows])
    y = np.array([r["scatter"] for r in rows], float)
    npos, nneg = int(y.sum()), int((1 - y).sum())
    if npos < MIN_CLASS or nneg < MIN_CLASS:
        calib = st_mod.active_calibration(st)
        st["calibration"] = {"mode": "prior", "coef": calib["coef"],
                             "tau": calib["tau"],
                             "tau_source": "prior-placeholder",
                             "n_units": len(rows),
                             "note": f"class imbalance (pos={npos}, neg={nneg}): "
                                     f"keeping pooled prior",
                             "warnings": warnings,
                             "phi_bands": phi_band_table(rows),
                             "self_checks": self_checks(st, rows),
                             "fitted_at": dt.date.today().isoformat()}
        st_mod.save_state(ws, st)
        return st["calibration"]

    w = fit_logit(X, y)
    se = coef_se(X, w)
    coef = {"intercept": round(float(w[0]), 2), "log_nMR": round(float(w[1]), 2),
            "KA": round(float(w[2]), 2), "GA": round(float(w[3]), 2)}
    coef_se_d = {"intercept": None, "log_nMR": round(float(se[1]), 2),
                 "KA": round(float(se[2]), 2), "GA": round(float(se[3]), 2)}
    result = {"mode": "local", "coef": coef, "coef_se": coef_se_d,
              "tau": round(float(y.mean()), 3), "tau_source": "local-base-rate",
              "n_units": len(rows), "base_rates": {"pos": npos, "neg": nneg},
              "cv_auc": _cv_auc(rows)}
    if warnings:
        result["warnings"] = warnings
    st["calibration"] = {**result, "phi_bands": phi_band_table(rows),
                         "self_checks": self_checks(st, rows),
                         "fitted_at": dt.date.today().isoformat()}
    st_mod.save_state(ws, st)
    return result
