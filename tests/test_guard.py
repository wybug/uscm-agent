"""R1' evaluation semantics: verdict ladder, thresholds, no lookahead."""
from uscm import state as st_mod
from uscm.guard import (apply_merge, comment_text, evaluate_merge,
                        init_replay, process_merge)
from uscm.model import p_scatter, prior_coef

SCHEME = {"type": "flat2"}
CALIB = {"mode": "prior", "coef": prior_coef(), "tau": 0.35,
         "tau_source": "prior-placeholder"}


def m(subject, files, sha="deadbeef", date="2026-01-05T09:00:00+00:00"):
    return {"sha": sha, "date": date, "subject": subject}, files


def base_state():
    return {"version": 1,
            "config": {"feature_patterns": None, "tau": None},
            "repos": {"r1": {"path": "/tmp/r1", "scheme": dict(SCHEME),
                             "head": None}},
            "features": {}, "processed": {"r1": []}, "flags": [],
            "stats": {"merges": 0, "flags": 0}, "calibration": None}


def seed_feature(st, key, nmr, units, authors):
    st["features"][key] = {"units": {u: 1 for u in units}, "nMR": nmr,
                           "authors": authors, "repos": {"r1": nmr},
                           "sizes": [2] * nmr, "first": "2025-01-01",
                           "last": "2025-12-01"}


def test_ok_no_feature_key():
    st = base_state()
    mg, files = m("chore: deps", ["a/b/x.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["verdict"] == "OK" and v["reason"] == "no-feature-key"


def test_ok_first_merge_of_feature():
    st = base_state()
    mg, files = m("Merge (--story=000001)", ["a/b/x.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["verdict"] == "OK" and v["reason"] == "feature-first-merge"


def test_pass_no_new_unit():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    mg, files = m("Merge (--story=000001)", ["a/b/x.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["verdict"] == "PASS" and v["reason"] == "no-new-unit"


def test_pass_new_unit_below_tau():
    st = base_state()
    seed_feature(st, "S000001", 1, ["a/b"], {"Alice": 1})
    mg, files = m("Merge (--story=000001)", ["a/b/x.go", "c/d/y.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    # nMR=1, single author: P = sigmoid(-1.01 + 0 - 0.61) ~ 0.165 < 0.35
    assert v["verdict"] == "PASS" and v["reason"] == "new-unit-below-tau"
    assert v["new_units"] == ["c/d"]


def test_flag_new_unit_above_tau():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    mg, files = m("Merge (--story=000001)", ["a/b/x.go", "c/d/y.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    # nMR=6, single author: P = sigmoid(-1.01 + 0.93*ln6 - 0.61) ~ 0.51 > 0.35
    assert v["verdict"] == "FLAG"
    assert v["P"] > CALIB["tau"] and v["new_units"] == ["c/d"]
    txt = comment_text(v)
    assert "R1'" in txt and "S000001" in txt and "c/d" in txt
    zh = comment_text(v, "zh")
    assert "反散落护栏" in zh


def test_author_dispersion_raises_p():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 1, "Bob": 1, "Carol": 4})
    mg, files = m("Merge (--story=000001)", ["a/b/x.go", "c/d/y.go"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    concentrated = base_state()
    seed_feature(concentrated, "S000001", 6, ["a/b"], {"Alice": 6})
    v2 = evaluate_merge(concentrated, CALIB, "r1", mg, files)
    # GA is concentration; dispersed authorship (low GA) raises P (beta_GA < 0)
    assert v["ga"] < 1.0 and v2["ga"] == 1.0
    assert v["P"] > v2["P"] > 0.3


def test_sequential_replay_no_lookahead():
    """Each verdict uses only merges strictly before it."""
    st = base_state()
    calib = CALIB
    verdicts = []
    for i, unit in enumerate(["a/b", "c/d", "e/f"]):
        mg = {"sha": f"sha{i}", "date": f"2026-01-0{i+1}T09:00:00+00:00",
              "subject": "Merge (--story=000001)"}
        v = process_merge(st, calib, "r1", mg, [f"{unit}/x.go"], "Alice")
        verdicts.append(v)
    assert verdicts[0]["verdict"] == "OK"           # first merge
    assert verdicts[1].get("nMR_prev") == 1
    assert verdicts[2].get("nMR_prev") == 2
    f = st["features"]["S000001"]
    assert f["nMR"] == 3 and set(f["units"]) == {"a/b", "c/d", "e/f"}


def test_front_scheme_page_units_only():
    st = base_state()
    st["repos"]["r1"]["scheme"] = {"type": "front"}
    seed_feature(st, "S000001", 6, ["page:orders"], {"Alice": 6})
    mg, files = m("Merge (--story=000001)",
                  ["src/api/order.ts", "src/components/Btn.tsx"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["verdict"] == "OK" and v["reason"] == "no-source-units"
    mg2, files2 = m("Merge (--story=000001)",
                    ["src/views/orders/x.tsx", "src/api/order.ts"])
    files2.append("src/views/profile/y.tsx")
    v2 = evaluate_merge(st, CALIB, "r1", mg2, files2)
    assert set(v2["units"]) == {"page:orders", "page:profile"}
    assert v2["new_units"] == ["page:profile"]


def test_apply_merge_updates_state():
    st = base_state()
    mg, files = m("Merge (--story=000009)", ["a/b/x.go"])
    apply_merge(st, "r1", mg, "S000009", files, "Alice")
    f = st["features"]["S000009"]
    assert f["nMR"] == 1 and f["authors"] == {"Alice": 1}
    assert st["processed"]["r1"] == ["deadbeef"]


def test_init_replay_on_tiny_repo(ws, tiny_repo):
    from conftest import make_merge
    make_merge(tiny_repo, 1, ["core/src/main/java/com/x/core/A.java"],
               "Alice", "2025-05-01T10:00:00+00:00")
    make_merge(tiny_repo, 2, ["core/src/main/java/com/x/core/A2.java"],
               "Alice", "2025-05-02T10:00:00+00:00")
    make_merge(tiny_repo, 3, ["api/src/main/java/com/x/api/B.java"],
               "Bob", "2025-05-03T10:00:00+00:00")
    cfg = st_mod.load_config(ws)
    s = init_replay(ws, cfg, [str(tiny_repo)], None)
    assert s["repos"]["svc-demo"]["scheme"] == "multi"
    assert s["features"] == 3 and s["merges"] == 3
    st = st_mod.load_state(ws)
    assert st["features"]["S000003"]["nMR"] == 1
