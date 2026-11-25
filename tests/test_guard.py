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


# ------------------------------------------------------------------ R4' --
from uscm.guard import r4_resumption  # noqa: E402


def seed_with_files(st, key, touched, last, nmr=2):
    seed_feature(st, key, nmr, ["svc"], {"Alice": nmr})
    st["features"][key]["files"] = {f: 1 for f in touched}
    st["features"][key]["last"] = last


def test_r4_triggers_on_resumption_retouch():
    st = base_state()
    seed_with_files(st, "S000001",
                    ["svc/Risk.java", "svc/RiskService.java"], "2025-08-12")
    v = r4_resumption(st["features"]["S000001"], "2025-08-26",
                      ["svc/Risk.java", "svc/RiskService.java"])
    assert v and v["kind"] == "r4" and v["gap_days"] == 14
    assert v["files"] == 2 and v["overlap"] == 2


def test_r4_normal_rhythm_not_flagged():
    st = base_state()
    seed_with_files(st, "S000001", ["svc/A.java"], "2025-08-12")
    assert r4_resumption(st["features"]["S000001"], "2025-08-16",
                         ["svc/A.java", "svc/B.java"]) is None


def test_r4_extension_into_new_files_not_flagged():
    st = base_state()
    seed_with_files(st, "S000001", ["svc/A.java"], "2025-08-01")
    # quiet 15 days, but the patch is mostly NEW files (1/4 re-touched)
    assert r4_resumption(st["features"]["S000001"], "2025-08-16",
                         ["svc/new1.java", "svc/new2.java", "svc/new3.java",
                          "svc/A.java"]) is None


def test_r4_empty_or_oversize_patch_not_flagged():
    st = base_state()
    seed_with_files(st, "S000001", ["svc/A.java"], "2025-08-01")
    assert r4_resumption(st["features"]["S000001"], "2025-08-20", []) is None
    six = [f"svc/F{i}.java" for i in range(6)]
    seed_with_files(st, "S000002", six, "2025-08-01")
    assert r4_resumption(st["features"]["S000002"], "2025-08-20", six) is None


def test_r4_backward_compat_without_file_history():
    st = base_state()
    seed_feature(st, "S000001", 3, ["svc"], {"Alice": 3})   # no "files" key
    assert r4_resumption(st["features"]["S000001"], "2026-01-01",
                         ["svc/A.java", "svc/B.java"]) is None


def test_r4_process_merge_flags_and_tracks_files():
    st = base_state()
    mg1, f1 = m("Merge (--story=000001)", ["src/main/java/svc/risk/A.java", "src/main/java/svc/risk/B.java"],
                date="2025-01-05T10:00:00+00:00")
    v1 = process_merge(st, CALIB, "r1", mg1, f1, "Alice", replay=True)
    assert v1["r4"] is None                       # first landing
    assert st["features"]["S000001"]["files"] == {"src/main/java/svc/risk/A.java": 1,
                                                  "src/main/java/svc/risk/B.java": 1}
    mg2, f2 = m("Merge (--story=000001)", ["src/main/java/svc/risk/A.java", "src/main/java/svc/risk/B.java"],
                sha="cafe0001", date="2025-01-25T10:00:00+00:00")
    v2 = process_merge(st, CALIB, "r1", mg2, f2, "Alice", replay=True)
    assert v2["r4"] and v2["r4"]["gap_days"] == 20
    r4_flags = [x for x in st["flags"] if x.get("kind") == "r4"]
    assert len(r4_flags) == 1 and r4_flags[0]["story"] == "S000001"
    assert st["features"]["S000001"]["files"]["src/main/java/svc/risk/A.java"] == 2


# ---------------------------------------------------- data-warehouse (dw) --

def test_dw_layers_are_normative_subject_is_the_unit():
    """One business subject across layers is one landing; a second subject
    is the new unit R1' judges."""
    st = base_state()
    st["repos"]["r1"]["scheme"] = {"type": "dw"}
    st["config"]["feature_patterns"] = [("Merge branch 'feature/(\\d{5,})'",
                                         "S{0}")]
    seed_feature(st, "S1000003", 6, ["sales.cust"], {"Alice": 6})
    mg, files = m("Merge branch 'feature/1000003' into 'master'",
                  ["init/dw/dml/dataworks/sales_cdm/ods_sales_cust/a.sql",
                   "init/dw/dml/dataworks/sales_cdm/dwd_sales_cust/b.sql",
                   "init/dw/dml/dataworks/sales_cdm/dws_sales_cust/c.sql"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["units"] == ["sales.cust"] and v["verdict"] == "PASS"
    assert v["dw"]["layers"] == ["ods", "dwd", "dws"]
    assert v["warning"].startswith("data-warehouse script repo under pooled prior")
    mg2, files2 = m("Merge branch 'feature/1000003' into 'master'",
                    ["init/dw/dml/dataworks/sales_cdm/dws_sales_cust/c.sql",
                     "init/dw/dml/dataworks/sales_cdm/dws_sales_trd/t.sql",
                     "deploy/2026/Q1/20260113-1000003/mc/1000003_ali_cloud_mc_ddl_abc.sql"])
    v2 = evaluate_merge(st, CALIB, "r1", mg2, files2)
    assert v2["verdict"] == "FLAG" and v2["new_units"] == ["sales.trd"]
    assert v2["dw"] == {"layers": ["dws"], "units": 2, "scripts": 3,
                        "attributed": 2, "deploy": 1, "rollback": 0}
    # scripts that name no table: counted for size, never a landing
    mg3, files3 = m("Merge branch 'feature/1000003' into 'master'",
                    ["deploy/2026/Q1/20260311-1000003/mc/1000003_ali_cloud_mc_ddl_abc.sql"])
    v3 = evaluate_merge(st, CALIB, "r1", mg3, files3)
    assert v3["verdict"] == "OK" and v3["reason"] == "no-source-units"
    assert v3["dw"]["scripts"] == 1 and v3["dw"]["attributed"] == 0


def test_dw_multi_story_merge_is_attributed_to_the_dominant_story():
    st = base_state()
    st["repos"]["r1"]["scheme"] = {"type": "dw"}
    st["config"]["feature_patterns"] = [("/\\d{8}[-@](\\d{5,})/", "S{0}", "path")]
    mg, files = m("Merge branch 'branch_exp' into 'master'",
                  ["deploy/2023/Q3/20230816-1000005/dim_sales_cust_a.sql",
                   "deploy/2023/Q3/20230816-1000006/dwd_sales_cust_b.sql",
                   "deploy/2023/Q3/20230816-1000006/dws_sales_cust_c.sql"])
    v = evaluate_merge(st, CALIB, "r1", mg, files)
    assert v["story"] == "S1000006" and v["key_source"] == "path"
    assert v["path_keys"] == {"S1000005": 1, "S1000006": 2}
    assert v["reason"] == "feature-first-merge"


def test_dw_repo_replay_and_check_keyed_by_deploy_archive(ws, tiny_repo):
    """init -> check on a script repository: landings are keyed by the
    merge subject or, when that is bare, by the per-story deploy archive."""
    from conftest import land_merge
    from uscm.guard import check
    (ws / "uscm.toml").write_text(r"""
[[feature]]
regex = "Merge branch 'feature/(\\d{5,})'"
tag = "S{0}"

[[feature]]
regex = "/\\d{8}[-@](\\d{5,})/"
tag = "S{0}"
where = "path"
""")
    gl = "Merge branch 'feature/1000003' into 'master'"
    bare = "Merge branch 'branch_exp' into 'master'"
    land_merge(tiny_repo, "feature/1000003", gl,
               ["dw-script/ods/sales/cust/fs_ods_sales_cust_kafka2holo.sql",
                "dw-script/cdm/dim/sales/cust/mc/dim_sales_cust_merch_info.sql"],
               date="2025-03-05T10:00:00+00:00")
    for i in range(5):          # bare subjects, keyed by the deploy archive
        land_merge(tiny_repo, f"branch_exp_{i}", bare,
                   [f"deploy/2025/Q2/2025040{i + 1}-1000003/mc/"
                    f"1000003_ali_cloud_mc_dwd_sales_cust_{i}.sql"],
                   date=f"2025-04-0{i + 1}T10:00:00+00:00")
    s = init_replay(ws, st_mod.load_config(ws), [str(tiny_repo)], None)
    assert s["repos"]["svc-demo"]["scheme"] == "dw"
    assert s["repos"]["svc-demo"]["dw"] == {"scripts": 7, "attributed": 7}
    st = st_mod.load_state(ws)
    assert st["features"]["S1000003"]["nMR"] == 6       # 1 subject + 5 path keys
    assert set(st["features"]["S1000003"]["units"]) == {"sales.cust"}
    # a merge not yet folded in: a new business subject -> R1' FLAG, tier T2
    sha = land_merge(tiny_repo, "branch_exp_9", bare,
                     ["deploy/2026/Q1/20260113-1000003/mc/"
                      "1000003_ali_cloud_mc_dws_sales_trd_trd_ddl_abc.sql"],
                     date="2026-01-13T10:00:00+00:00")
    v = check(ws, "svc-demo", sha)
    assert v["verdict"] == "FLAG" and v["new_units"] == ["sales.trd"]
    assert v["key_source"] == "path" and v["nMR_prev"] == 6
    assert v["dw"]["deploy"] == 1 and v["dw"]["layers"] == ["dws"]
    assert v["review"]["tier"] == "T2"
