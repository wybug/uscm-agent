"""Statistical core: regime law, logistic fit, AUC, Phi quantile budgets.

The placement-regime law (USCM-CC paper, replacing Eq. 51):

    logit P(scatter) = b0 + b1*log(nMR) + b2*KA + b3*GA

Pooled cold-start prior lives in ``uscm/priors/regime_pooled.json``.
"""
from __future__ import annotations

import json
import math
from importlib import resources

import numpy as np

NMR_BANDS = [(1, 1), (2, 3), (4, 8), (9, None)]


def load_prior() -> dict:
    data = (resources.files("uscm") / "priors" / "regime_pooled.json").read_text()
    return json.loads(data)


def prior_coef(prior: dict | None = None) -> dict:
    p = prior or load_prior()
    c = p["coef"]
    return {"intercept": c["intercept"], "log_nMR": c["log_nMR"],
            "KA": c["KA"], "GA": c["GA"]}


def ga_of(author_counts: dict) -> float:
    """Author concentration in [0, 1]: 1 = single author (max concentration)."""
    ka = len(author_counts)
    if ka <= 1:
        return 1.0
    pa = np.array(list(author_counts.values()), float)
    pa = pa / pa.sum()
    ent = -(pa * np.log(pa)).sum()
    return 1.0 - float(ent) / math.log(ka)


def p_scatter(coef: dict, nmr: int, ka: int, ga: float) -> float:
    z = (coef["intercept"] + coef["log_nMR"] * math.log(max(nmr, 1))
         + coef["KA"] * max(ka, 1) + coef["GA"] * ga)
    return 1.0 / (1.0 + math.exp(-z))


def feats(nmr: float, ka: float, ga: float) -> list[float]:
    return [1.0, math.log(max(nmr, 1)), ka, ga]


def fit_logit(X: np.ndarray, y: np.ndarray, lam: float = 1.0, iters: int = 60):
    """Ridge-regularized logistic regression via IRLS."""
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        z = X @ w
        p = 1 / (1 + np.exp(-z))
        Wt = np.clip(p * (1 - p), 1e-6, None)
        H = X.T @ (X * Wt[:, None]) + lam * np.eye(X.shape[1])
        g = X.T @ (y - p) - lam * w
        step = np.linalg.solve(H, g)
        w += step
        if np.abs(step).max() < 1e-8:
            break
    return w


def coef_se(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Approximate standard errors from the final IRLS Hessian (lam=1)."""
    z = X @ w
    p = 1 / (1 + np.exp(-z))
    Wt = np.clip(p * (1 - p), 1e-6, None)
    H = X.T @ (X * Wt[:, None]) + np.eye(X.shape[1])
    return np.sqrt(np.diag(np.linalg.inv(H)))


def auc(y, s) -> float | None:
    """Rank-based AUC; None if one class is empty."""
    y = np.asarray(y, float)
    s = np.asarray(s, float)
    pos, neg = s[y == 1], s[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), float)
    sv = s[order]
    i = 0
    while i < len(sv):
        j = i
        while j + 1 < len(sv) and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return float((ranks[y == 1].sum() - len(pos) * (len(pos) + 1) / 2)
                 / (len(pos) * len(neg)))


def band_of(nmr: int) -> str:
    for lo, hi in NMR_BANDS:
        if lo <= nmr and (hi is None or nmr <= hi):
            return f"{lo}" if lo == hi else (f"{lo}-{hi}" if hi else f"{lo}+")


def shrunk_p90(local_values: list[float], prior_p90: float | None,
               k: int = 15) -> tuple[float | None, float]:
    """Small-sample P90 via shrinkage toward a prior (change-cost eval).

    threshold = w * P90(local) + (1 - w) * prior,  w = n / (n + k).
    Returns (threshold, w); (None, 0.0) when no local data. With n >= k the
    local quantile stands on its own (w = 1). Keeps early-history / thin-band
    budgets from thrashing between 1 and 7 while true signals still cross.
    """
    n = len(local_values)
    if n == 0:
        return None, 0.0
    q = float(np.percentile(local_values, 90))
    if prior_p90 is None or n >= k:
        return q, 1.0
    w = n / (n + k)
    return w * q + (1 - w) * float(prior_p90), w


def phi_band_table(rows: list[dict], q: float = 0.9, min_n: int = 3,
                   shrink_k: int = 15) -> dict:
    """Local Phi budget: per-nMR-band P90 of Phi.

    ``rows``: dicts with keys nMR, Phi. Bands need >= min_n observations to
    emit anything; bands with min_n <= n < shrink_k emit a *shrunk* P90
    blended toward the all-features P90 prior (flagged ``shrunk: true`` with
    weight ``w``), so thin bands (e.g. the 9+ band with 3 stories) get a
    usable low-confidence budget instead of none. Phi has no universal law -
    budgets remain strictly local quantities, the prior is only a variance
    reducer.
    """
    by_band: dict[str, list[float]] = {}
    for r in rows:
        by_band.setdefault(band_of(int(r["nMR"])), []).append(float(r["Phi"]))
    prior = (float(np.percentile([v for vs in by_band.values() for v in vs],
                                 q * 100))
             if sum(len(v) for v in by_band.values()) >= min_n else None)
    out: dict[str, dict] = {}
    for b, v in sorted(by_band.items()):
        if len(v) < min_n:
            out[b] = {"p90": None, "n": len(v)}
            continue
        p90, w = shrunk_p90(v, prior, k=shrink_k)
        out[b] = {"p90": round(p90, 1), "n": len(v),
                  "shrunk": len(v) < shrink_k, "w": round(w, 2)}
    return out
