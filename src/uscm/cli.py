"""Command-line interface: uscm <init|calibrate|check|watch|advise|report|synth|mcp>."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import __version__
from . import state as st_mod


def _ws() -> Path:
    return Path.cwd()


def _j(x) -> None:
    print(json.dumps(x, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- commands --

def cmd_init(a) -> None:
    ws = _ws()
    cfg = st_mod.load_config(ws)
    from .guard import init_replay
    s = init_replay(ws, cfg, a.repos, a.since)
    if a.json:
        _j(s)
        return
    for name, r in s["repos"].items():
        print(f"  {name:24s} scheme={r['scheme']:6s} merges={r['merges']}")
    print(f"features: {s['features']}   merges replayed: {s['merges']}   "
          f"historical R1' flags: {s['flags']}")
    print("next: uscm calibrate   (then: uscm watch / check / advise / report)")


def cmd_calibrate(a) -> None:
    from .calibrate import calibrate
    res = calibrate(_ws(), a.min_units)
    if a.json:
        _j(res)
        return
    mode = res["mode"]
    c = res["coef"]
    print(f"mode: {mode}   units: {res['n_units']}   "
          f"tau: {res['tau']} ({res['tau_source']})")
    print(f"coef: intercept={c['intercept']}  log_nMR={c['log_nMR']}  "
          f"KA={c['KA']}  GA={c['GA']}")
    if res.get("cv_auc") is not None:
        print(f"local fit 5-fold CV AUC: {res['cv_auc']}")
    if res.get("note"):
        print(f"note: {res['note']}")


def cmd_check(a) -> None:
    from .guard import check, comment_text
    v = check(_ws(), a.repo, a.sha)
    if a.json:
        out = dict(v)
        if v["verdict"] == "FLAG":
            out["comment"] = comment_text(v, "zh" if a.zh else "en")
        _j(out)
        return
    print(f"{v['verdict']}: {v.get('reason', '')}  {v['story']}  "
          f"{v['repo']}#{v['sha'][:8]}")
    if "P" in v:
        print(f"  P(scatter)={v['P']}  tau={v['tau']}  nMR_prev={v['nMR_prev']}  "
              f"GA={v['ga']}  new_units={v['new_units']}")
    if v.get("warning"):
        print(f"  warning: {v['warning']}")
    if v["verdict"] == "FLAG":
        print("  " + comment_text(v, "zh" if a.zh else "en"))


def cmd_watch(a) -> None:
    from .guard import watch
    res = watch(_ws(), fetch=a.fetch)
    if a.json:
        _j(res)
        return
    print(f"new merges: {res['new_merges']}   new flags: {res['new_flags']}   "
          f"(calibration: {res['calibration_mode']})")
    for f in res["flags"][-10:]:
        print(f"  FLAG [{f['date']}] {f['repo']}#{f['sha'][:8]} P={f['P']} "
              f"{f['story']} new={','.join(f['new_units'][:3])}")


def cmd_advise(a) -> None:
    ws = _ws()
    st = st_mod.load_state(ws)
    if st is None:
        raise SystemExit("no workspace state: run `uscm init` first")
    calib = st_mod.active_calibration(st)
    from .advise import advise_feature, rank_features, render_detail
    if a.story:
        rep = advise_feature(st, calib, a.story)
        if rep is None:
            raise SystemExit(f"unknown feature {a.story}")
        if a.json:
            _j(rep)
        else:
            print(render_detail(rep))
        return
    rows = rank_features(st, calib, top=a.top)
    if a.json:
        _j(rows)
        return
    hdr = (f"{'story':10s} {'nMR':>3s} {'Phi':>3s} {'KA':>2s} {'GA':>4s} "
           f"{'P':>5s} {'>tau':>5s} {'budget':>6s} {'anom':>4s} {'flags':>5s}")
    print(hdr)
    for r in rows:
        print(f"{r['story']:10s} {r['nMR']:3d} {r['Phi']:3d} {r['KA']:2d} "
              f"{r['GA']:4.2f} {r['P']:5.2f} {str(r['above_tau']):>5s} "
              f"{'ALARM' if r['phi_budget_alarm'] else '-':>6s} "
              f"{'R3' if r['r3'] else '-':>4s} {r['flags']:5d}")


def cmd_report(a) -> None:
    from .report import monthly_report
    res = monthly_report(_ws(), a.month)
    print(f"-> {res['path']}   ({res['flags']} flags in {res['month']})")


def cmd_synth(a) -> None:
    from .synth import generate
    m = generate(a.out, seed=a.seed, n_repos=a.repos, n_features=a.features,
                 months=a.months)
    if a.json:
        _j({k: v for k, v in m.items() if k != "features"})
        return
    print(f"synthetic system -> {a.out}")
    print(f"repos: {len(m['repos'])}  features: {len(m['features'])}  "
          f"merges: {m['merges']}  planted scatter rate: {m['scatter_rate']}")
    print("try: cd into a scratch dir, then "
          "`uscm init --repos '<outdir>/*' && uscm calibrate`")


def cmd_mcp(a) -> None:
    from .mcp import serve
    serve()


# ------------------------------------------------------------------ parser --

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uscm",
        description="Placement-decision agent from the USCM-CC change-cost "
                    "model (R1' anti-scatter guardrail, R2' narrowing, "
                    "Phi budgets, R3' anomaly, two-layer calibration).")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scan repos, replay history, build state")
    s.add_argument("--repos", nargs="*", help="repo paths/globs (else uscm.toml)")
    s.add_argument("--since", help="only merges since date (YYYY-MM-DD)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("calibrate", help="local refit + tau + Phi bands + self-checks")
    s.add_argument("--min-units", type=int, default=40)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_calibrate)

    s = sub.add_parser("check", help="single-merge R1' evaluation (read-only)")
    s.add_argument("repo")
    s.add_argument("sha")
    s.add_argument("--zh", action="store_true", help="Chinese comment text")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("watch", help="incremental pass over new merges")
    s.add_argument("--fetch", action="store_true", help="git fetch --all first")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_watch)

    s = sub.add_parser("advise", help="per-feature decision report / risk ranking")
    s.add_argument("--story", help="feature key for detailed report")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_advise)

    s = sub.add_parser("report", help="monthly guardrail report (markdown)")
    s.add_argument("--month", help="YYYY-MM (default: latest activity)")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("synth", help="generate a deterministic synthetic system")
    s.add_argument("--out", required=True)
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--repos", type=int, default=8)
    s.add_argument("--features", type=int, default=60)
    s.add_argument("--months", type=int, default=18)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_synth)

    s = sub.add_parser("mcp", help="run the MCP server (stdio) for coding agents")
    s.set_defaults(fn=cmd_mcp)
    return p


def main(argv=None) -> None:
    a = build_parser().parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
