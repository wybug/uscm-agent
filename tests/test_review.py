"""Review tier ladder: triggers, thresholds, no-lookahead quantiles, stats."""
from uscm.guard import evaluate_merge, process_merge
from uscm.model import prior_coef
from uscm.review import (advise_review_next, comment_text, review_decision,
                         reviewstats, thresholds)

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
            "reviews": {"log": [], "file_counts": []},
            "stats": {"merges": 0, "flags": 0}, "calibration": None}


def seed_feature(st, key, nmr, units, authors, sizes=None):
    st["features"][key] = {"units": {u: 1 for u in units}, "nMR": nmr,
                           "authors": authors, "repos": {"r1": nmr},
                           "sizes": sizes or [2] * nmr,
                           "first": "2025-01-01", "last": "2025-12-01"}


def decide(st, subject, files):
    mg, fl = m(subject, files)
    v = evaluate_merge(st, CALIB, "r1", mg, fl)
    return v, review_decision(st, CALIB, v, fl, SCHEME)


# ------------------------------------------------------------------ ladder --

def test_t1_no_feature_key():
    st = base_state()
    v, d = decide(st, "chore: deps", ["a/b/x.go"])
    assert d["tier"] == "T1" and d["triggers"] == ["no-feature-key"]


def test_t3_shape_gate_precedes_feature_gates():
    """Oversized/multi-unit first merges and unkeyed bulk drops drew T1
    before the reorder - the shape is the problem regardless of key."""
    st = base_state()
    files = [f"a/b/f{i:02d}.go" for i in range(20)]
    v, d = decide(st, "chore: bulk import", files)          # no key
    assert d["tier"] == "T3" and d["triggers"] == ["oversized-merge"]
    v, d = decide(st, "Merge (--story=000001)", files)      # feature's first
    assert d["tier"] == "T3" and "first landing" in d["focus"][-1]
    v, d = decide(st, "Merge (--story=000001)",
                 ["a/b/x.go", "c/d/y.go", "e/f/z.go"])      # first, 3 units
    assert d["tier"] == "T3" and "multi-unit-merge" in d["triggers"]


def test_unattributed_multi_unit_is_not_t3():
    """No key -> no attribution -> no decompose claim (R1' makes the same
    demand); per-unit focus instead. Release-line rollup remnants look
    exactly like this."""
    st = base_state()
    v, d = decide(st, "chore: rollup sync",
                 ["a/b/x.go", "c/d/y.go", "e/f/z.go"])      # 3 units, small
    assert d["tier"] == "T1" and d["triggers"] == ["no-feature-key"]
    assert any("per unit" in f for f in d["focus"])


def test_t1_first_merge_sets_placement_focus():
    st = base_state()
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go"])
    assert d["tier"] == "T1" and d["triggers"] == ["feature-first-merge"]
    assert d["focus"][0].startswith("placement")


def test_t0_small_single_existing_unit():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "a/b/y.go"])
    assert d["tier"] == "T0" and d["triggers"] == []
    assert d["required"] == [] and "correctness" in comment_text(d)


def test_t1_sync_of_existing_units_not_t0():
    st = base_state()
    seed_feature(st, "S000001", 2, ["a/b", "c/d"], {"Alice": 2})
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "c/d/y.go"])
    assert d["tier"] == "T1"          # 2 existing units: standard, not auto
    assert any("per unit" in f for f in d["focus"])


def test_sync_of_scattered_feature_is_not_t3():
    """A sync across a feature's existing landings is atomic (Prop. 9):
    decompose is not an executable remedy, so it never routes to T3."""
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b", "c/d", "e/f"], {"Alice": 6})
    v, d = decide(st, "Merge (--story=000001)",
                  ["a/b/x.go", "c/d/y.go", "e/f/z.go"])
    assert v["new_units"] == []       # pure sync, no expansion
    assert d["tier"] == "T1"
    assert any("per unit" in f for f in d["focus"])


def test_t2_on_r1_flag():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "c/d/y.go"])
    assert v["verdict"] == "FLAG"
    assert d["tier"] == "T2" and d["triggers"] == ["new-unit-above-tau"]
    assert any("placement rationale" in r for r in d["required"])
    assert "放置理由" in comment_text(d, "zh")


def test_t2_on_prospective_phi_budget():
    st = base_state()
    st["calibration"] = {"phi_bands": {"2-3": {"p90": 2}}}
    seed_feature(st, "S000001", 2, ["a/b", "c/d"], {"Alice": 2})
    # nMR=2 -> P below tau (PASS), but phi_after=3 crosses band P90=2
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "e/f/y.go"])
    assert v["verdict"] == "PASS" and v["reason"] == "new-unit-below-tau"
    assert d["tier"] == "T2" and d["triggers"] == ["phi-budget"]
    assert d["phi_after"] == 3 and d["phi_band_p90"] == 2


def test_t3_multi_unit_merge_dominates_flag():
    st = base_state()
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    v, d = decide(st, "Merge (--story=000001)",
                  ["a/b/x.go", "c/d/y.go", "e/f/z.go"])
    assert v["verdict"] == "FLAG"                    # would be T2 ...
    assert d["tier"] == "T3"                         # ... but shape wins
    assert "multi-unit-merge" in d["triggers"]
    assert any("decomposition" in r for r in d["required"])
    assert "分解" in comment_text(d, "zh")


def test_t3_oversized_fallback_threshold():
    st = base_state()                                # no history -> fallback 15
    seed_feature(st, "S000001", 2, ["a/b"], {"Alice": 2})
    files = [f"a/b/f{i:02d}.go" for i in range(15)]
    v, d = decide(st, "Merge (--story=000001)", files)
    assert d["tier"] == "T3" and d["triggers"] == ["oversized-merge"]
    assert d["thresholds"]["split_files"] == 15


# ------------------------------------------------------------ quantiles -----

def test_local_quantiles_and_no_lookahead():
    st = base_state()
    st["reviews"]["file_counts"] = [1] * 30 + [2] * 10   # 40 prior merges
    thr = thresholds(st)
    assert thr["history"] == 40 and thr["split_files"] == 2
    assert thr["auto_max_files"] == 1
    seed_feature(st, "S000001", 2, ["a/b"], {"Alice": 2})
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "a/b/y.go"])
    assert d["tier"] == "T3"          # 2 files >= local P90(=2)
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go"])
    assert d["tier"] == "T0"          # 1 file <= local P50(=1)


def test_degenerate_quantiles_keep_ladder_apart():
    st = base_state()
    st["reviews"]["file_counts"] = [1] * 40             # P90 == P50 == 1
    thr = thresholds(st)
    assert thr["split_files"] == 2 and thr["auto_max_files"] == 1
    assert thr["degenerate"] is True    # surfaced, not silently patched
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    v, d = decide(st, "Merge (--story=000001)", ["c/d/x.go"])   # FLAG path
    assert d["tier"] == "T2"          # 1-file merge is never oversized
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "a/b/y.go"])
    assert d["tier"] == "T3"          # 2 files >= P50+1


def test_size_gate_local_p90_cannot_loosen_ceiling():
    """Machete repo: everyone writes 40-file MRs; the local P90 must not
    neutralize the configured absolute ceiling (paper Table 9/10)."""
    st = base_state()
    st["reviews"]["file_counts"] = [10] * 22 + [40] * 18  # P50=10, P90=40
    thr = thresholds(st)
    assert thr["split_files"] == 15          # min(P90, cfg) - tighten only
    assert thr["auto_max_files"] == 10 and thr["degenerate"] is False
    seed_feature(st, "S000001", 6, ["a/b"], {"Alice": 6})
    files = [f"a/b/f{i:02d}.go" for i in range(30)]
    v, d = decide(st, "Merge (--story=000001)", files)
    assert d["tier"] == "T3"                 # 30 files over the ceiling
    v, d = decide(st, "Merge (--story=000001)",
                 [f"a/b/f{i:02d}.go" for i in range(12)])
    assert d["tier"] == "T1"                 # 12 <= 15, but > P50 -> no auto


def test_config_ceiling_wins_over_local_quantiles():
    st = base_state()
    st["config"]["review"] = {"split_files": 2}
    st["reviews"]["file_counts"] = [3] * 20 + [5] * 20   # P50=3, P90=5
    thr = thresholds(st)
    assert thr["split_files"] == 2 and thr["auto_max_files"] == 1
    assert thr["degenerate"] is False


def test_config_overrides():
    st = base_state()
    st["config"]["review"] = {"split_units": 2, "local_quantiles": False}
    seed_feature(st, "S000001", 2, ["a/b", "c/d"], {"Alice": 2})
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go", "e/f/y.go"])
    assert d["tier"] == "T3" and d["thresholds"]["split_units"] == 2


def test_r3_anomaly_blocks_t0():
    st = base_state()
    seed_feature(st, "S000001", 7, ["a/b"], {"Alice": 7},
                sizes=[2, 2, 2, 2, 9, 9, 9])
    v, d = decide(st, "Merge (--story=000001)", ["a/b/x.go"])
    assert d["tier"] == "T1"          # size anomaly: no auto-pass
    assert any("anomaly" in f for f in d["focus"])


# --------------------------------------------------------- process/record ---

def test_process_merge_records_review_log():
    st = base_state()
    mg = {"sha": "s1", "date": "2026-01-01T09:00:00+00:00",
          "subject": "Merge (--story=000001)"}
    v = process_merge(st, CALIB, "r1", mg, ["a/b/x.go"], "Alice", replay=True)
    assert v["review"]["tier"] == "T1"                # first merge
    assert st["reviews"]["log"][0]["tier"] == "T1"
    assert st["reviews"]["file_counts"] == [1]
    mg2 = {"sha": "s2", "date": "2026-01-02T09:00:00+00:00",
           "subject": "Merge (--story=000001)"}
    v2 = process_merge(st, CALIB, "r1", mg2, ["a/b/x.go"], "Alice")
    assert len(st["reviews"]["log"]) == 2
    assert st["reviews"]["file_counts"] == [1, 1]


# -------------------------------------------------------- advise / stats ----

def test_advise_review_next_branches():
    st = base_state()
    st["calibration"] = {"phi_bands": {"4-8": {"p90": 2}}}
    seed_feature(st, "S000001", 7, ["a/b", "c/d"], {"Alice": 7})
    rn = advise_review_next(st, CALIB, "S000001")
    # phi=2 >= band P90=2: staying put is still T2 (budget), new unit T2 too
    assert rn["stay_in_existing_units"]["tier"].startswith("T2")
    assert rn["introduce_new_unit"]["tier"] == "T2"
    assert rn["introduce_new_unit"]["phi_after"] == 3


def test_reviewstats_distribution_and_lift():
    st = base_state()
    st["calibration"] = {"phi_bands": {"2-3": {"p90": 2}}}
    seed_feature(st, "S000001", 6, ["a/b", "c/d", "e/f", "g/h", "i/j", "k/l"],
                 {"Alice": 6})                        # heavy: N1=6
    seed_feature(st, "S000002", 2, ["a/b"], {"Bob": 2})
    st["reviews"]["log"] = [
        {"story": "S000001", "tier": "T2", "triggers": ["new-unit-above-tau"],
         "n_files": 2, "units_in_mr": 2},
        {"story": "S000002", "tier": "T0", "triggers": [], "n_files": 1,
         "units_in_mr": 1},
        {"story": "S000002", "tier": "T1", "triggers": [], "n_files": 2,
         "units_in_mr": 1},
    ]
    r = reviewstats(st)
    assert r["merges"] == 3
    assert r["distribution"] == {"T0": 1, "T1": 1, "T2": 1, "T3": 0}
    assert r["t0_share"] == round(1 / 3, 3)
    assert r["features"]["triggered_t2t3"]["n"] == 1
    assert r["features"]["triggered_t2t3"]["heavy"] == 1
    assert r["features"]["no_t2t3"]["n"] == 1
    assert r["features"]["no_t2t3"]["heavy"] == 0
    # untriggered heavy_rate is 0 -> lift undefined (None), not a crash
    assert r["lift"] is None
    assert r["size_gate"]["history"] == 0        # final thresholds reported


def test_reviewstats_empty_log():
    r = reviewstats(base_state())
    assert r["merges"] == 0 and "re-run" in r["note"]
