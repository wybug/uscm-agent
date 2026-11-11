from uscm.advise import r3_anomaly, rank_features
from uscm import state as st_mod
from uscm.model import prior_coef


def test_r3_anomaly():
    a = r3_anomaly([2, 2, 2, 2, 8, 9, 10])
    assert a and a["anomaly"] is True
    b = r3_anomaly([2, 2, 2, 2, 2, 2, 2])
    assert b and b["anomaly"] is False
    assert r3_anomaly([2, 2, 3]) is None          # too short
    assert r3_anomaly([0, 0, 0, 0]) is None       # zero baseline


def _state():
    calib = {"mode": "prior", "coef": prior_coef(), "tau": 0.35,
             "tau_source": "prior-placeholder"}
    st = {"version": 1, "config": {}, "repos": {"r": {"scheme": {"type": "flat2"}}},
          "features": {}, "processed": {"r": []}, "flags": [], "stats": {},
          "calibration": None}
    st["features"]["S1"] = {"units": {"a": 3, "b": 1}, "nMR": 8,
                            "authors": {"Alice": 8}, "repos": {"r": 8},
                            "sizes": [2, 2, 2, 2, 2, 9, 10, 11],
                            "first": "2025-01-01", "last": "2026-01-01"}
    st["features"]["S2"] = {"units": {"c": 4}, "nMR": 2,
                            "authors": {"Alice": 1, "Bob": 1}, "repos": {"r": 2},
                            "sizes": [2, 2], "first": "2025-01-01",
                            "last": "2026-01-01"}
    return st, calib


def test_rank_features_orders_by_risk():
    st, calib = _state()
    rows = rank_features(st, calib, top=10)
    assert rows[0]["story"] == "S1"          # high nMR, concentrated -> highest P
    assert rows[0]["r3"] is True             # sizes 9,10,11 vs baseline 2
    assert rows[0]["above_tau"] is True
    assert rows[1]["story"] == "S2" and rows[1]["r3"] is False


# ------------------------------------------- R3'-down / shrunk budget ----
from uscm.advise import advise_feature, render_detail  # noqa: E402


def test_r3_down_anomaly():
    a = r3_anomaly([4, 4, 4, 4, 1, 1, 1])
    assert a["anomaly"] is False and a["anomaly_down"] is True
    b = r3_anomaly([4, 4, 4, 4, 2, 2, 8])
    assert b["anomaly_down"] is False


def test_advise_renders_r4_events():
    st, calib = _state()
    st["flags"].append({"kind": "r4", "date": "2025-06-01", "repo": "r",
                        "sha": "abc", "story": "S1", "gap_days": 13,
                        "files": 3, "overlap": 3, "subject": "rework"})
    rep = advise_feature(st, calib, "S1")
    assert rep["r4_events"] and rep["r4_events"][0]["gap_days"] == 13
    txt = render_detail(rep)
    assert "R4' rework: 1 resurrection patch(es)" in txt
