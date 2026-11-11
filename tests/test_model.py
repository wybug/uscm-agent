import numpy as np

from uscm.model import (auc, band_of, coef_se, feats, fit_logit, ga_of,
                        load_prior, phi_band_table, p_scatter, prior_coef)


def test_prior_shipped():
    p = load_prior()
    c = prior_coef(p)
    assert c["intercept"] == -1.01 and c["log_nMR"] == 0.93
    assert c["GA"] == -0.61
    assert p["provenance"]["transfer_auc_mean"] > 0.6


def test_ga_bounds():
    assert ga_of({"a": 10}) == 1.0
    assert abs(ga_of({"a": 5, "b": 5})) < 1e-9          # uniform = no concentration
    assert 0.0 < ga_of({"a": 3, "b": 1}) < 0.5           # skewed = concentrated


def test_p_scatter_extremes():
    flat = {"intercept": 0.0, "log_nMR": 0.0, "KA": 0.0, "GA": 0.0}
    assert abs(p_scatter(flat, 1, 1, 1.0) - 0.5) < 1e-12
    c = prior_coef()
    assert p_scatter(c, 6, 1, 1.0) > p_scatter(c, 2, 1, 1.0)   # nMR raises P
    assert p_scatter(c, 6, 1, 0.2) > p_scatter(c, 6, 1, 1.0)   # GA lowers P


def test_fit_logit_recovers_planted_directions():
    rng = np.random.default_rng(11)
    b = np.array([-1.0, 0.9, 0.0, -0.6])
    X = np.column_stack([
        np.ones(3000),
        np.log(rng.integers(1, 13, 3000).astype(float)),
        rng.integers(1, 4, 3000).astype(float),
        rng.uniform(0, 1, 3000)])
    pr = 1 / (1 + np.exp(-(X @ b)))
    y = (rng.uniform(size=3000) < pr).astype(float)
    w = fit_logit(X, y)
    assert w[1] > 0.5            # log_nMR positive
    assert w[3] < -0.35          # GA negative
    assert abs(w[2]) < 0.25      # KA ~ 0
    se = coef_se(X, w)
    assert (se > 0).all()
    a = auc(y, X @ w)
    assert a is not None and a > 0.6


def test_auc_known_values():
    assert auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auc([0, 1], [0.5, 0.5]) == 0.5
    assert auc([1, 1], [0.3, 0.4]) is None


def test_bands_and_phi_table():
    assert [band_of(n) for n in (1, 2, 3, 4, 8, 9, 40)] == \
        ["1", "2-3", "2-3", "4-8", "4-8", "9+", "9+"]
    rows = [{"nMR": 2, "Phi": float(i)} for i in range(1, 13)] + \
           [{"nMR": 5, "Phi": 2.0}, {"nMR": 5, "Phi": 3.0}]
    t = phi_band_table(rows)
    assert t["2-3"]["n"] == 12 and t["2-3"]["p90"] is not None
    assert t["4-8"]["p90"] is None          # < min_n observations
    assert "1" not in t                     # empty band not materialized


def test_feats_layout():
    assert feats(4, 2, 0.5) == [1.0, np.log(4), 2.0, 0.5]


# --------------------------------------------------------- shrunk P90 ----
import pytest  # noqa: E402

from uscm.model import phi_band_table, shrunk_p90  # noqa: E402


def test_shrunk_p90_small_n_blends_prior():
    val, w = shrunk_p90([8.0, 9.0, 10.0], prior_p90=7.0, k=15)
    assert w == pytest.approx(3 / 18)
    assert val == pytest.approx(w * 9.8 + (1 - w) * 7.0)   # q90(3 vals)=9.8


def test_shrunk_p90_large_n_is_raw():
    vals = [float(x) for x in range(1, 21)]
    val, w = shrunk_p90(vals, prior_p90=99.0, k=15)
    assert w == 1.0 and val == float(np.percentile(vals, 90))


def test_shrunk_p90_edge_cases():
    assert shrunk_p90([], prior_p90=7.0) == (None, 0.0)
    val, w = shrunk_p90([5.0, 6.0], prior_p90=None, k=15)  # no prior: raw
    assert w == 1.0 and val == 5.9


def test_phi_band_table_shrinks_thin_bands():
    rows = [{"nMR": 1, "Phi": 2}] * 25 + [{"nMR": 9, "Phi": 10},
                                          {"nMR": 9, "Phi": 12},
                                          {"nMR": 9, "Phi": 14}]
    t = phi_band_table(rows)
    assert t["1"]["shrunk"] is False            # n=25 >= 15: local stands
    assert t["1"]["p90"] == 2.0
    assert t["9+"]["shrunk"] is True and t["9+"]["p90"] is not None
    assert t["9+"]["w"] == pytest.approx(3 / 18, abs=0.01)
    t2 = phi_band_table([{"nMR": 9, "Phi": 10}, {"nMR": 9, "Phi": 12}])
    assert t2["9+"]["p90"] is None              # below emit minimum (3)
