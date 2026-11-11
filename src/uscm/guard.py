"""R1' anti-scatter guardrail (USCM-CC paper, Section 3.10).

Rule: a merge is FLAGged when it (a) carries a feature key, (b) lands in
source units, (c) the feature has prior merges, (d) the merge introduces at
least one placement unit new to the feature, and (e) the feature's
P(scatter) - computed only from information available *before* this merge -
exceeds the system base rate tau.

Verdict ladder: FLAG / PASS / OK (with skip reason). Evaluations never see
future data: ``evaluate_merge`` reads the feature table as-is, and the
replay loop applies each merge only after judging it.
"""
from __future__ import annotations

from . import state as st_mod
from .features import (compile_patterns, feature_key, git, head_of, list_merges,
                       merge_author, merge_files, merges_after)
from .model import ga_of, p_scatter
from .modules import source_files, units_of
from . import review as rv_mod


def evaluate_merge(st: dict, calib: dict, repo: str, merge: dict,
                   files: list[str]) -> dict:
    """Pre-event R1' evaluation of one merge. Does not mutate state."""
    scheme = st["repos"][repo]["scheme"]
    patterns = compile_patterns(st["config"].get("feature_patterns"))
    key = feature_key(merge["subject"], patterns)
    out = {"date": merge["date"][:10], "repo": repo, "sha": merge["sha"],
           "subject": merge["subject"][:100], "story": key}
    if not key:
        return {**out, "verdict": "OK", "reason": "no-feature-key"}
    units = units_of(scheme, files)
    out["units"] = sorted(units)
    if not units:
        return {**out, "verdict": "OK", "reason": "no-source-units"}
    f = st["features"].get(key)
    if not f or f["nMR"] < 1:
        return {**out, "verdict": "OK", "reason": "feature-first-merge"}
    new_units = sorted(units - set(f["units"]))
    ka = len(f.get("authors", {})) or 1
    ga = ga_of(f.get("authors", {}))
    P = p_scatter(calib["coef"], f["nMR"], ka, ga)
    out.update({"P": round(P, 3), "tau": calib["tau"], "nMR_prev": f["nMR"],
                "ka": ka, "ga": round(ga, 3), "new_units": new_units,
                "phi_prev": len(f["units"])})
    if scheme["type"] == "front" and calib["mode"] == "prior":
        out["warning"] = ("front-end repo under pooled prior: recalibrate "
                          "locally before trusting this threshold")
    if not new_units:
        return {**out, "verdict": "PASS", "reason": "no-new-unit"}
    if P > calib["tau"]:
        return {**out, "verdict": "FLAG", "reason": "new-unit-above-tau"}
    return {**out, "verdict": "PASS", "reason": "new-unit-below-tau"}


def comment_text(v: dict, lang: str = "en") -> str:
    new_units = ", ".join(v["new_units"][:4])
    if lang == "zh":
        return (f"【R1′ 反散落护栏】本合并将为功能 {v['story']} 引入新放置单元 "
                f"[{new_units}]，其散落概率 P={v['P']:.0%} 已越过系统基率 "
                f"τ={v['tau']:.0%}（nMR={v['nMR_prev']}，GA={v['ga']:.2f}）。"
                f"请说明放置理由，或放入既有单元 / 先缩小放置选项（R2′）。")
    return (f"[R1' anti-scatter guardrail] This merge introduces new placement "
            f"unit(s) [{new_units}] for feature {v['story']}, whose "
            f"P(scatter)={v['P']:.0%} exceeds the system base rate "
            f"tau={v['tau']:.0%} (nMR={v['nMR_prev']}, GA={v['ga']:.2f}). "
            f"State the placement rationale, or place into an existing unit / "
            f"narrow the options first (R2').")


def apply_merge(st: dict, repo: str, merge: dict, key: str | None,
                files: list[str], author: str | None) -> None:
    """Fold one merge into the feature table (call AFTER judging it)."""
    if key:
        units = units_of(st["repos"][repo]["scheme"], files)
        if units:
            st_mod.update_feature(st, key, repo, units, author,
                                  len(source_files(files)), merge["date"][:10])
    st["processed"].setdefault(repo, []).append(merge["sha"])
    st["stats"]["merges"] += 1


def process_merge(st: dict, calib: dict, repo: str, merge: dict, files: list[str],
                  author: str | None, replay: bool = False) -> dict:
    """Evaluate -> review tier -> maybe flag -> apply + record."""
    v = evaluate_merge(st, calib, repo, merge, files)
    dec = rv_mod.review_decision(st, calib, v, files,
                                 st["repos"][repo]["scheme"])
    v["review"] = dec
    if v["verdict"] == "FLAG":
        st["flags"].append({"date": v["date"], "repo": repo, "sha": merge["sha"],
                            "story": v["story"], "P": v["P"], "tau": v["tau"],
                            "nMR_prev": v["nMR_prev"],
                            "new_units": v["new_units"][:6],
                            "subject": v["subject"], "replay": replay})
        st["stats"]["flags"] = len(st["flags"])
    apply_merge(st, repo, merge, v.get("story"), files, author)
    rv_mod.record(st, dec, v)
    return v


# -------------------------------------------------------------- full pass --

def collect_repo(repo: str, path, since: str | None, mainline: bool = True,
                 unit_style: str = "module",
                 skip_segments=None) -> tuple[list[dict], dict]:
    """Merges (oldest first, with files/author loaded) + detected scheme."""
    merges = list_merges(path, since, mainline=mainline)
    all_files: list[str] = []
    for m in merges:
        m["files"] = merge_files(path, m["sha"])
        m["author"] = merge_author(path, m["sha"])
        all_files.extend(m["files"])
    from .modules import apply_unit_style, detect_scheme
    scheme = detect_scheme(all_files) if all_files else {"type": "flat2"}
    scheme = apply_unit_style(scheme, all_files, unit_style, skip_segments)
    return merges, scheme


def init_replay(ws, cfg: dict, repo_args: list[str] | None,
                since_arg: str | None):
    """Build workspace state from scratch: detect schemes, replay history."""
    patterns = repo_args if repo_args else cfg.get("repos") or []
    repos = st_mod.resolve_repos(patterns)
    if not repos:
        raise SystemExit("no repositories found: pass --repos PATH... or set "
                         "repos = [...] in uscm.toml")
    since = since_arg or cfg.get("since")
    mainline = cfg.get("mainline", True)
    st = st_mod.new_state(ws, cfg, repos)
    timeline = []
    for name, path in repos.items():
        merges, scheme = collect_repo(name, path, since, mainline=mainline,
                                      unit_style=cfg.get("unit_style", "module"),
                                      skip_segments=cfg.get("skip_segments"))
        st["repos"][name]["scheme"] = scheme
        for m in merges:
            timeline.append((name, m))
        st["repos"][name]["head"] = head_of(path)
    timeline.sort(key=lambda x: (x[1]["date"], x[0], x[1]["sha"]))
    calib = st_mod.active_calibration(None)
    for name, m in timeline:
        process_merge(st, calib, name, m, m["files"], m.get("author"),
                      replay=True)
    st_mod.save_state(ws, st)
    return summarize(st, repos)


def watch(ws, fetch: bool = False) -> dict:
    """Incremental pass: judge new merges since each repo's recorded head."""
    st = st_mod.load_state(ws)
    if st is None:
        raise SystemExit("no workspace state: run `uscm init` first")
    calib = st_mod.active_calibration(st)
    cfg_since = (st["config"] or {}).get("since")
    mainline = (st["config"] or {}).get("mainline", True)
    new_flags = []
    merges_seen = 0
    for name, rec in st["repos"].items():
        path = rec["path"]
        head = rec.get("head")
        if head is None:
            continue
        if fetch:
            git(path, "fetch", "--all", "--quiet")
        proc = set(st["processed"].get(name, []))
        for m in merges_after(path, head, cfg_since, mainline=mainline):
            if m["sha"] in proc:
                continue
            files = merge_files(path, m["sha"])
            author = merge_author(path, m["sha"])
            v = process_merge(st, calib, name, m, files, author, replay=False)
            proc.add(m["sha"])
            merges_seen += 1
            if v["verdict"] == "FLAG":
                new_flags.append(st["flags"][-1])
        st["repos"][name]["head"] = head_of(path)
    st_mod.save_state(ws, st)
    return {"new_merges": merges_seen, "new_flags": len(new_flags),
            "flags": new_flags, "stats": st["stats"],
            "calibration_mode": calib["mode"]}


def check(ws, repo_arg: str, sha: str) -> dict:
    """Read-only single-merge evaluation (for CI / pre-merge hooks)."""
    st = st_mod.load_state(ws)
    if st is None:
        raise SystemExit("no workspace state: run `uscm init` first")
    matches = [n for n in st["repos"] if n == repo_arg or n.endswith("/" + repo_arg)
               or n.endswith(repo_arg)]
    if len(matches) != 1:
        known = ", ".join(sorted(st["repos"]))
        raise SystemExit(f"repo '{repo_arg}' not unique/known (repos: {known})")
    name = matches[0]
    path = st["repos"][name]["path"]
    p = git(path, "log", "-1", "--date=iso-strict",
            "--format=%ad%x09%s", sha)
    parts = p.stdout.split("\t", 1)
    if len(parts) != 2:
        raise SystemExit(f"sha {sha} not found in {name}")
    merge = {"sha": sha, "date": parts[0], "subject": parts[1].strip()}
    files = merge_files(path, sha)
    calib = st_mod.active_calibration(st)
    v = evaluate_merge(st, calib, name, merge, files)
    v["review"] = rv_mod.review_decision(st, calib, v, files,
                                         st["repos"][name]["scheme"])
    return v


def summarize(st: dict, repos) -> dict:
    return {"repos": {n: {"scheme": st["repos"][n]["scheme"]["type"],
                          "merges": len(st["processed"].get(n, []))}
                      for n in repos},
            "features": len(st["features"]),
            "merges": st["stats"]["merges"],
            "flags": st["stats"]["flags"]}
