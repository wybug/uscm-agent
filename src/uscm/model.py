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


def phi_band_table(rows: list[dict], q: float = 0.9, min_n: int = 10) -> dict:
    """Local Phi budget: per-nMR-band P90 of Phi.

    ``rows``: dicts with keys nMR, Phi. Bands with < min_n observations get
    None (budget alarm stays off for that band) - Phi has no universal law,
    budgets are strictly local quantities.
    """
    by_band: dict[str, list[float]] = {}
    for r in rows:
        by_band.setdefault(band_of(int(r["nMR"])), []).append(float(r["Phi"]))
    return {b: {"p90": (round(float(np.percentile(v, q * 100)), 1)
                        if len(v) >= min_n else None),
                "n": len(v)}
            for b, v in sorted(by_band.items())}
