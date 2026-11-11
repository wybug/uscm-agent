"""Review decisions: route each merge to a review tier (T0-T3).

A review checklist says what to look at; it cannot say where scarce
reviewer attention should go. The structural signals answer that: from
pre-event, name-level signals only (no blob fetch), every merge gets a
tier that moves attention *up* the value ladder (alignment > correctness
> style/automated) instead of just demanding more of it.

- T3 split-first  : one merge spanning >= split_units placement units, or
                    >= local P90 files-per-merge (fallback 15). The remedy
                    is decomposition along placement units, not a longer
                    review (acceptance cost grows superlinearly in the
                    number of touched modules).
- T2 deep+place   : R1' FLAG, or the prospective landing count crosses the
                    local Phi-band budget. Senior review focused on
                    placement/alignment; a placement rationale (choice vs
                    alternatives, sync plan with existing landings) is
                    required - the PR description becomes a decision record.
- T1 standard     : carries a story key, no structural trigger.
- T0 auto+sample  : single existing unit, no new unit, <= local P50 files
                    (fallback 5), no size anomaly - machine checks plus
                    periodic sampling. T0 speaks to the *placement*
                    dimension only; it never certifies correctness.

Merges without a feature key (and a feature's first merge) get T1 with a
reason. File-count thresholds derive from already-replayed history only -
each merge's count is appended after it is judged - so replay stays free
of lookahead.
"""
from __future__ import annotations

import numpy as np

from .model import band_of, ga_of, p_scatter
from .modules import source_files, units_of

DEFAULTS = {"split_units": 3, "split_files": 15, "auto_max_files": 5,
            "local_quantiles": True}
MIN_HISTORY = 40          # merges of file-count history before local quantiles
TIERS = ("T0", "T1", "T2", "T3")


def review_cfg(st: dict) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update(((st.get("config") or {}).get("review")) or {})
    return cfg


def thresholds(st: dict) -> dict:
    """Size-gate thresholds in force.

    Two instruments, two epistemics (paper Table 9/10): landing count has no
    universal law, so its budget is a pure local P90; review size has an
    externally calibrated ceiling (detection collapses beyond ~400 lines),
    so the local P90 may only *tighten* the configured ceiling - never
    loosen it. The P50+1 floor keeps the ladder coherent on degenerate
    low-spread distributions (a pure P90 there would alarm ~every merge);
    that case is surfaced as ``degenerate`` rather than silently patched,
    mirroring the label-degeneracy warning in ``calibrate``.
    """
    cfg = review_cfg(st)
    counts = (st.get("reviews") or {}).get("file_counts") or []
    split_files, auto_max = cfg["split_files"], cfg["auto_max_files"]
    degenerate = False
    if cfg["local_quantiles"] and len(counts) >= MIN_HISTORY:
        p50 = max(1, int(np.quantile(counts, 0.5)))
        p90 = max(1, int(np.quantile(counts, 0.9)))
        split_files = min(p90, cfg["split_files"])   # tighten only, never loosen
        if split_files <= p50:                       # no spread above the median
            split_files = min(p50 + 1, cfg["split_files"])
            degenerate = p90 <= p50
        auto_max = p50
    auto_max = min(auto_max, split_files - 1)        # T0 ceiling below T3 trigger
    return {"split_units": cfg["split_units"], "split_files": split_files,
            "auto_max_files": auto_max, "history": len(counts),
            "degenerate": degenerate}


def _phi_budget(st: dict, nmr_next: int):
    bands = (st.get("calibration") or {}).get("phi_bands") or {}
    return bands.get(band_of(nmr_next), {}).get("p90")


def review_decision(st: dict, calib: dict, v: dict, files: list[str],
                    scheme: dict) -> dict:
    """Pre-event review tier for one merge. Reads state; never mutates."""
    from .advise import r3_anomaly      # lazy: advise pulls this module too
    src = source_files(files)
    units = units_of(scheme, files)
    thr = thresholds(st)
    out = {"n_files": len(src), "units_in_mr": len(units), "triggers": []}
    key = v.get("story")
    reason = v.get("reason")

    # T3 shape gate first, for EVERY merge. Oversized applies always (a
    # property of the merge alone). Multi-unit requires *attribution*: the
    # "decompose along units" remedy presumes an authorial bundle - a
    # keyed merge that expands the footprint to >= split_units (new units,
    # or the feature's first drop). A sync of existing landings is atomic
    # by construction (splitting it mid-flight creates silent inconsistency,
    # Proposition 9), and an unattributed multi-unit merge (no key - often
    # release-line rollup remnants) cannot be told apart from one: both get
    # per-unit review focus at T1/T2 instead. This mirrors R1', which also
    # demands a feature key before making placement claims.
    triggers = []
    if out["n_files"] >= thr["split_files"]:
        triggers.append("oversized-merge")
    if len(units) >= thr["split_units"]:
        expanding = (reason == "feature-first-merge"
                     or bool(v.get("new_units")))
        if expanding:
            triggers.append("multi-unit-merge")
    if triggers:
        out.update(tier="T3", triggers=triggers,
                   focus=["decompose along placement units",
                          "one capability per merge, landings closed "
                          "inside single units"],
                   required=["decomposition plan"],
                   thresholds={"split_units": thr["split_units"],
                               "split_files": thr["split_files"]})
        if reason == "feature-first-merge":
            out["focus"].append(
                "this merge also sets the feature's first landing")
        return out

    if not key or reason in ("no-feature-key", "feature-first-merge",
                             "no-source-units"):
        out.update(tier="T1", triggers=[reason],
                   focus=["correctness and test evidence"],
                   required=["test evidence"])
        if len(units) >= 2:
            out["focus"].append("multi-unit merge: review per unit, "
                                "check cross-unit consistency")
        if reason == "feature-first-merge":
            out["focus"].insert(
                0, "placement: this merge sets the feature's first landing")
        return out

    f = st["features"].get(key) or {}
    new_units = v.get("new_units") or []
    phi_prev = v.get("phi_prev", len(f.get("units", {})))
    phi_after = phi_prev + len(new_units)
    budget = _phi_budget(st, v.get("nMR_prev", f.get("nMR", 1)) + 1)
    phi_alarm = budget is not None and phi_after >= budget
    r3 = r3_anomaly(f.get("sizes", []))
    anomaly = bool(r3 and r3["anomaly"])

    if v["verdict"] == "FLAG":
        tier, triggers = "T2", ["new-unit-above-tau"]
    elif phi_alarm:
        tier, triggers = "T2", ["phi-budget"]
    elif (not new_units and len(units) == 1
          and out["n_files"] <= thr["auto_max_files"] and not anomaly):
        tier, triggers = "T0", []
        out["thresholds"] = {"auto_max_files": thr["auto_max_files"]}
    else:
        tier, triggers = "T1", []

    if tier == "T2":
        out.update(P=v.get("P"), tau=v.get("tau"), phi_after=phi_after,
                   phi_band_p90=budget,
                   focus=["placement rationale vs alternative units",
                          "sync with the feature's existing landings"],
                   required=[f"placement rationale (candidates, choice, "
                             f"sync plan for {phi_prev} existing landings)"])
        if v.get("warning"):
            out["warning"] = v["warning"]
    elif tier == "T1":
        out.update(focus=["correctness and test evidence"],
                   required=["test evidence"])
        if len(units) >= 2:
            out["focus"].append("multi-unit merge: review per unit, "
                                "check cross-unit consistency")
        if anomaly:
            out["focus"].append("feature shows a size anomaly - check scope")
    else:
        out.update(focus=[], required=[],
                   note="structural dimension only; never certifies "
                        "correctness")
    out["tier"], out["triggers"] = tier, triggers
    return out


def comment_text(dec: dict, lang: str = "en") -> str:
    t, n, u = dec["tier"], dec["n_files"], dec["units_in_mr"]
    trig = ", ".join(dec["triggers"]) or "-"
    if lang == "zh":
        if t == "T3":
            return (f"【评审决策 T3｜先分解】本合并一次触及 {u} 个放置单元、"
                    f"{n} 个源文件（触发：{trig}）。请沿放置单元拆分为多个 MR"
                    "——每个 MR 落点封闭在单一单元内——再进入评审；"
                    "体量不可评审时，更细的评审不是解法。")
        if t == "T2":
            why = ("R1′：P(散落)={:.0%} 越过 τ={:.0%}".format(dec["P"], dec["tau"])
                   if "P" in dec else
                   "Φ 预算：落点数将达 {}，越过本带 P90={}".format(
                       dec["phi_after"], dec["phi_band_p90"]))
            return (f"【评审决策 T2｜深评+放置讨论】{why}。请随 MR 附放置理由"
                    "（候选单元、为何选此、与其余落点如何同步），"
                    "由资深评审把关对齐层。")
        if t == "T0":
            return ("【评审决策 T0｜机器+抽样】单单元、无新落点、小体量："
                    "结构维度放行，周期抽样即可（本档不判断正确性，"
                    "正确性评审按团队策略执行）。")
        base = "【评审决策 T1｜标准评审】结构维度无触发：聚焦正确性与测试证据。"
        return base + f"（原因：{trig}）" if dec["triggers"] else base
    if t == "T3":
        return (f"[review T3 | split first] This merge spans {u} placement "
                f"units and {n} source files (triggers: {trig}). Decompose "
                "along placement units - one capability per merge, landings "
                "closed inside single units - then review; a longer review "
                "is not the remedy for an unreviewable shape.")
    if t == "T2":
        why = (f"R1': P(scatter)={dec['P']:.0%} exceeds tau={dec['tau']:.0%}"
               if "P" in dec else
               f"Phi budget: landings would reach {dec['phi_after']}, "
               f"crossing the band P90={dec['phi_band_p90']}")
        return (f"[review T2 | deep + placement] {why}. Attach a placement "
                "rationale (candidate units, why this one, sync plan with "
                "existing landings); senior review owns the alignment layer.")
    if t == "T0":
        return ("[review T0 | auto + sampling] Single existing unit, no new "
                "landing, small: structural dimension passes to machine "
                "checks plus periodic sampling (this tier never certifies "
                "correctness).")
    base = "[review T1 | standard] No structural trigger: focus on correctness and test evidence."
    return base + f" (reason: {trig})" if dec["triggers"] else base


def record(st: dict, dec: dict, v: dict) -> None:
    """Append one judged merge to the review log (call AFTER the decision)."""
    rev = st.setdefault("reviews", {"log": [], "file_counts": []})
    rev.setdefault("log", []).append({
        "date": v.get("date"), "repo": v.get("repo"), "sha": v.get("sha"),
        "story": v.get("story"), "tier": dec["tier"],
        "triggers": dec["triggers"], "n_files": dec["n_files"],
        "units_in_mr": dec["units_in_mr"]})
    rev.setdefault("file_counts", []).append(dec["n_files"])


def reviewstats(st: dict) -> dict:
    """Replay-log summary: tier distribution + outcome lift.

    Lift mirrors the calibrate.py precision self-check: features that drew
    >=1 T2/T3 merge vs the rest, scored on the *final* feature table
    (heavy scatter = N1 >= 6 or Phi in the top tercile). Correlational,
    same caveat as the R1' lift.
    """
    log = (st.get("reviews") or {}).get("log") or []
    if not log:
        return {"merges": 0, "note": "review log empty - old workspace; "
                "re-run `uscm init` to rebuild with review tiers"}
    dist = {t: 0 for t in TIERS}
    per_story: dict[str, dict] = {}
    for e in log:
        dist[e["tier"]] = dist.get(e["tier"], 0) + 1
        if e.get("story"):
            s = per_story.setdefault(e["story"], {"t23": 0, "merges": 0})
            s["merges"] += 1
            if e["tier"] in ("T2", "T3"):
                s["t23"] += 1
    phis = [len(f["units"]) for f in st["features"].values() if f["nMR"] >= 2]
    top3 = float(np.quantile(phis, 2 / 3)) if len(phis) >= 3 else None
    buckets = {"triggered_t2t3": {"n": 0, "heavy": 0},
               "no_t2t3": {"n": 0, "heavy": 0}}
    for key, f in st["features"].items():
        if f["nMR"] < 2:
            continue
        s = per_story.get(key)
        b = buckets["triggered_t2t3"] if (s and s["t23"] >= 1) \
            else buckets["no_t2t3"]
        b["n"] += 1
        n1 = len(f["units"])
        if n1 >= 6 or (top3 is not None and n1 >= top3):
            b["heavy"] += 1
    for b in buckets.values():
        b["heavy_rate"] = round(b["heavy"] / b["n"], 3) if b["n"] else None
    lift = None
    tr, un = buckets["triggered_t2t3"], buckets["no_t2t3"]
    if tr["n"] and un["n"] and un["heavy"] and un["heavy_rate"]:
        lift = round(tr["heavy_rate"] / un["heavy_rate"], 3)
    thr = thresholds(st)
    return {"merges": len(log), "distribution": dist,
            "t0_share": round(dist["T0"] / len(log), 3),
            "features": buckets, "lift": lift,
            "heavy": "N1>=6 or Phi top tercile (nMR>=2 features)",
            "size_gate": {"split_files": thr["split_files"],
                          "auto_max_files": thr["auto_max_files"],
                          "degenerate": thr["degenerate"],
                          "history": thr["history"]}}


def advise_review_next(st: dict, calib: dict, key: str) -> dict | None:
    """What tier the feature's *next* merge would draw, per branch."""
    f = st["features"].get(key)
    if not f:
        return None
    nmr, ka = f["nMR"], len(f.get("authors", {})) or 1
    ga = ga_of(f.get("authors", {}))
    p_next = p_scatter(calib["coef"], nmr + 1, ka, ga)
    budget = _phi_budget(st, nmr + 1)
    phi_now = len(f["units"])
    stay_t2 = budget is not None and phi_now >= budget
    new_t2 = p_next > calib["tau"] or (budget is not None
                                       and phi_now + 1 >= budget)
    return {"P_next": round(p_next, 3), "tau": calib["tau"],
            "phi_now": phi_now, "phi_band_p90": budget,
            "stay_in_existing_units": {
                "tier": "T2 (phi budget)" if stay_t2 else "T0/T1 (size gate)"},
            "introduce_new_unit": {
                "tier": "T2" if new_t2 else "T1", "phi_after": phi_now + 1}}
