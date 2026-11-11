"""Monthly guardrail report: trigger rate, flagged-feature evolution,
calibration summary with self-checks, and the boundary declaration."""
from __future__ import annotations

import datetime as dt

from . import state as st_mod

BOUNDARY = ("Boundary: this model provides directions, rankings, probabilities "
            "and budget alarms only. No absolute cost prediction; no "
            "feature-level defect prediction (tested null); all thresholds "
            "require monthly local recalibration.")


def monthly_report(ws, month: str | None = None) -> dict:
    st = st_mod.load_state(ws)
    if st is None:
        raise SystemExit("no workspace state: run `uscm init` first")
    flags = st.get("flags", [])
    if month is None:
        month = (max((f["date"] for f in flags), default="") or
                 dt.date.today().strftime("%Y-%m"))[:7]
    in_month = [f for f in flags if f["date"][:7] == month]
    flagged_stories = {f["story"] for f in in_month}
    evolved = [s for s in flagged_stories
               if (feat := st["features"].get(s)) and feat["nMR"] >= 3]
    calib = st.get("calibration") or {}

    L = [f"# USCM-CC guardrail report - {month}", "",
         f"- merges processed (lifetime): {st['stats']['merges']}",
         f"- guardrail flags in {month}: {len(in_month)}"
         f" (lifetime {len(flags)})",
         f"- distinct flagged features: {len(flagged_stories)}, still "
         f"evolving (nMR>=3): {len(evolved)}", "",
         "## Flags this month",
         ""]
    for f in in_month[-30:]:
        if f.get("kind") == "r4":
            L.append(f"- [{f['date']}] {f['repo']}#{f['sha'][:8]} R4' rework "
                     f"{f['story']} gap={f['gap_days']}d files={f['files']} "
                     f"re-touch={f['overlap']} | {f['subject'][:60]}")
        else:
            L.append(f"- [{f['date']}] {f['repo']}#{f['sha'][:8]} P={f['P']} "
                     f"tau={f['tau']} {f['story']} new_units="
                     f"{','.join(f['new_units'][:3])} | {f['subject'][:60]}")
    L += ["", "## Calibration", ""]
    if calib:
        L.append(f"- mode: {calib.get('mode')} (tau={calib.get('tau')}, "
                 f"{calib.get('tau_source')}, n_units={calib.get('n_units')}, "
                 f"fitted {calib.get('fitted_at')})")
        if calib.get("cv_auc") is not None:
            L.append(f"- local fit CV AUC: {calib['cv_auc']}")
        sc = calib.get("self_checks") or {}
        if sc.get("direction"):
            L.append(f"- self-check direction: {sc['direction']}")
        if sc.get("regime_drift"):
            L.append(f"- self-check drift: {sc['regime_drift']}")
        if sc.get("alarm_precision"):
            L.append(f"- self-check precision: {sc['alarm_precision']}")
    else:
        L.append("- not calibrated yet: pooled prior in force "
                 "(tau is a placeholder until `uscm calibrate`)")
    L += ["", "## Boundary declaration", "", BOUNDARY, ""]
    dest = ws / ".uscm" / "reports" / f"{month}.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(L))
    return {"path": str(dest), "month": month, "flags": len(in_month)}
