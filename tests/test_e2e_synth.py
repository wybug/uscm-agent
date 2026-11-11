"""End-to-end on the synthetic system:
synth -> init (replay) -> calibrate -> check -> watch -> advise -> report.
"""
import json

from conftest import make_merge
from uscm import state as st_mod
from uscm.advise import advise_feature, rank_features, render_detail
from uscm.calibrate import calibrate
from uscm.guard import check, init_replay, watch
from uscm.report import monthly_report
from uscm.synth import generate


def test_full_loop(tmp_path, monkeypatch):
    system = tmp_path / "system"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(ws)

    manifest = generate(str(system), seed=7, n_repos=8, n_features=60,
                        months=18)
    assert manifest["merges"] > 100
    assert manifest["repos"]["portal-web"] == "front"

    # ---- init: schemes detected, history replayed with frozen prior ----
    cfg = st_mod.load_config(ws)
    s = init_replay(ws, cfg, [str(system / "*")], None)
    schemes = {n: r["scheme"] for n, r in s["repos"].items()}
    assert schemes["svc-order"] == "multi"
    assert schemes["platform-common"] == "multi"
    assert schemes["gateway"] == "flat2"
    assert schemes["portal-web"] == "front"
    assert s["features"] >= 40

    st = st_mod.load_state(ws)
    replay_flags = st["flags"]
    assert len(replay_flags) >= 3
    for f in replay_flags:                    # every flag is a true R1' hit
        assert f["new_units"] and f["P"] > f["tau"] and f["replay"] is True

    # every replayed merge drew a review tier; counts append after judging
    log = st["reviews"]["log"]
    assert len(log) == s["merges"]
    assert all(e["tier"] in ("T0", "T1", "T2", "T3") for e in log)
    assert any(e["tier"] == "T2" for e in log)          # flags -> deep review
    from uscm.review import reviewstats
    rs = reviewstats(st)
    assert rs["merges"] == len(log)
    assert sum(rs["distribution"].values()) == len(log)

    # ---- calibrate: local law recovers the planted directions ----
    res = calibrate(ws)
    assert res["mode"] == "local"
    assert res["coef"]["log_nMR"] > 0.3       # planted 0.9
    assert res["coef"]["GA"] < -0.2           # planted -0.6
    assert 0.0 < res["tau"] < 1.0
    st = st_mod.load_state(ws)
    sc = st["calibration"]["self_checks"]["alarm_precision"]
    assert sc["flagged_heavy_share"] >= sc["unflagged_heavy_share"]

    # ---- check: historical sha already folded -> PASS (state moved on) ----
    old = replay_flags[0]
    v = check(ws, old["repo"], old["sha"])
    assert v["verdict"] == "PASS" and v["reason"] == "no-new-unit"
    assert v["review"]["tier"] in ("T0", "T1", "T2", "T3")

    # ---- live check + watch: continue top-risk features with a new unit ----
    top = rank_features(st, st_mod.active_calibration(st), top=5)
    assert top and all("P" in r for r in top)
    checked = []
    for row in top:
        feat = st["features"][row["story"]]
        num = int(row["story"][1:])
        used = set(feat["units"])
        unit = next((u for u in ("core", "api", "web") if u not in used), None)
        if unit is None:
            continue
        sha = make_merge(system / "svc-order", num,
                         [f"{unit}/src/main/java/com/x/{unit}/F{num}.java"],
                         "Alice", "2026-07-01T09:00:00+00:00")
        checked.append(check(ws, "svc-order", sha))
    assert any(v["verdict"] == "FLAG" for v in checked)

    w = watch(ws)
    assert w["new_merges"] >= len(checked) - 1
    assert w["new_flags"] >= 1
    assert w["calibration_mode"] == "local"

    # ---- advise + report ----
    st = st_mod.load_state(ws)
    rep = advise_feature(st, st_mod.active_calibration(st), top[0]["story"])
    assert rep["story"] == top[0]["story"]
    assert "phi_band_p90" in rep and "r3_anomaly" in rep
    assert rep["review_next"]["introduce_new_unit"]["tier"] in ("T1", "T2")
    txt = render_detail(rep)
    assert "Phi budget" in txt and "R2'" in txt and "review next merge" in txt

    r = monthly_report(ws)
    assert r["flags"] >= 1
    content = open(r["path"]).read()
    assert "Boundary" in content and "self-check" in content
