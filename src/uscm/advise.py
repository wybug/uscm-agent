"""Per-feature decision reports (R2' narrowing, Phi budget, R3' anomaly).

- R2' (narrow first): for features above tau, rank their existing placement
  units - changes kept inside existing units do not deepen scatter risk.
- Phi budget: alarm when a feature's landing count Phi crosses the local
  P90 of its nMR band (strictly local; no cross-system Phi bound exists).
- R3' (local anomaly): last >= 3 merges each materially larger than the
  feature's own size baseline - a statistical marker for human review,
  not proof of debt.
"""
from __future__ import annotations

import numpy as np

from . import state as st_mod
from .model import band_of, p_scatter


def r3_anomaly(sizes: list[int]) -> dict | None:
    if len(sizes) < 4:
        return None
    baseline = float(np.median(sizes[:-3]))
    if baseline <= 0:
        return None
    last3 = sizes[-3:]
    threshold = max(1.5 * baseline, baseline + 2)
    return {"baseline": round(baseline, 1), "last3": last3,
            "threshold": round(threshold, 1),
            "anomaly": all(s >= threshold for s in last3)}


def advise_feature(st: dict, calib: dict, key: str) -> dict | None:
    f = st["features"].get(key)
    if not f:
        return None
    nmr, ka = f["nMR"], len(f.get("authors", {})) or 1
    from .model import ga_of
    ga = ga_of(f.get("authors", {}))
    p_now = p_scatter(calib["coef"], nmr, ka, ga)
    p_next = p_scatter(calib["coef"], nmr + 1, ka, ga)
    phi = len(f["units"])
    band = band_of(nmr)
    bands = (st.get("calibration") or {}).get("phi_bands") or {}
    budget = bands.get(band, {}).get("p90")
    budget_alarm = budget is not None and phi >= budget
    units_ranked = sorted(f["units"].items(), key=lambda kv: -kv[1])
    above = p_now > calib["tau"]
    flagged = sum(1 for x in st.get("flags", []) if x["story"] == key)
    from .review import advise_review_next    # lazy: review imports r3_anomaly
    return {
        "story": key, "nMR": nmr, "Phi": phi, "KA": ka, "GA": round(ga, 3),
        "repos": sorted(f["repos"]), "units": units_ranked,
        "P_scatter_now": round(p_now, 3),
        "P_scatter_next_merge": round(p_next, 3),
        "tau": calib["tau"], "above_tau": above,
        "phi_band": band, "phi_band_p90": budget,
        "phi_budget_alarm": budget_alarm,
        "r2_narrowing": (units_ranked if above else None),
        "r3_anomaly": r3_anomaly(f.get("sizes", [])),
        "review_next": advise_review_next(st, calib, key),
        "guardrail_flags": flagged,
        "first": f.get("first"), "last": f.get("last"),
    }


def rank_features(st: dict, calib: dict, top: int = 10,
                  min_nmr: int = 2) -> list[dict]:
    from .model import ga_of
    rows = []
    for key, f in st["features"].items():
        if f["nMR"] < min_nmr:
            continue
        ka = len(f.get("authors", {})) or 1
        ga = ga_of(f.get("authors", {}))
        p = p_scatter(calib["coef"], f["nMR"], ka, ga)
        band = band_of(f["nMR"])
        bands = (st.get("calibration") or {}).get("phi_bands") or {}
        budget = bands.get(band, {}).get("p90")
        phi = len(f["units"])
        rows.append({"story": key, "nMR": f["nMR"], "Phi": phi, "KA": ka,
                     "GA": round(ga, 2), "P": round(p, 3),
                     "above_tau": p > calib["tau"],
                     "phi_budget_alarm": budget is not None and phi >= budget,
                     "r3": bool((r3 := r3_anomaly(f.get("sizes", [])))
                                and r3["anomaly"]),
                     "flags": sum(1 for x in st.get("flags", [])
                                  if x["story"] == key)})
    rows.sort(key=lambda r: (-r["P"], -r["Phi"]))
    return rows[:top]


def render_detail(rep: dict) -> str:
    L = [f"feature {rep['story']}  ({rep['first']} .. {rep['last']})",
         f"  nMR={rep['nMR']}  Phi={rep['Phi']}  KA={rep['KA']}  "
         f"GA={rep['GA']}  repos={','.join(rep['repos'])}",
         f"  P(scatter) now={rep['P_scatter_now']}  next merge="
         f"{rep['P_scatter_next_merge']}  (tau={rep['tau']}, "
         f"above: {'yes' if rep['above_tau'] else 'no'})"]
    if rep["phi_band_p90"] is not None:
        L.append(f"  Phi budget: band nMR {rep['phi_band']} P90="
                 f"{rep['phi_band_p90']} -> "
                 f"{'ALARM (Phi crossed)' if rep['phi_budget_alarm'] else 'within budget'}")
    else:
        L.append("  Phi budget: no local budget for this band yet "
                 "(needs >= 10 units in band)")
    if rep["r2_narrowing"]:
        cand = ", ".join(f"{u} (x{n})" for u, n in rep["r2_narrowing"][:6])
        L.append(f"  R2' narrowing: keep changes inside existing units -> {cand}")
    if rep["r3_anomaly"]:
        a = rep["r3_anomaly"]
        L.append(f"  R3' size anomaly: baseline={a['baseline']} "
                 f"last3={a['last3']} threshold={a['threshold']} -> "
                 f"{'FLAGGED' if a['anomaly'] else 'no'}")
    rn = rep.get("review_next")
    if rn:
        L.append(f"  review next merge: existing units -> "
                 f"{rn['stay_in_existing_units']['tier']}; new unit -> "
                 f"{rn['introduce_new_unit']['tier']} "
                 f"(P_next={rn['P_next']}, tau={rn['tau']}, "
                 f"phi_after={rn['introduce_new_unit']['phi_after']})")
    if rep["guardrail_flags"]:
        L.append(f"  guardrail flags on this feature: {rep['guardrail_flags']}")
    return "\n".join(L)
