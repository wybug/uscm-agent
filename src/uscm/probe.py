"""Workflow pre-analysis: classify a repository's branch workflow *before*
configuring uscm, so mainline/dialect/unit-style decisions are derived from
evidence instead of guesswork (read-only; no workspace state).

Why this exists (instrument-first, ``no instrument, no model``):

- **Landing structure.** The unit of change is a merge *onto a landing line*
  (mainline, develop, release trains). Repos with ``feature -> release ->
  master`` flows, fast-forward rollups and in-branch review iterations
  (refs/changes) cannot be measured by a naive first-parent walk of HEAD:
  keyed landings are inherited by every later line cut from the same base,
  and nested merges (review patchsets, syncs, feature->feature) pollute
  feature tables. :func:`probe` measures all of this and recommends either
  ``mainline = true`` (direct flow) or ``mainline = false`` on a *staged*
  clone whose nested merges are grafted out (recipe emitted).
- **Story dialect.** Digit-run shapes recurring in *source branch* names are
  ranked as ``[[feature]]`` regex candidates, with line-name contamination
  (release numbers like ``release-250903``) excluded per shape.
- **Unit style.** Module-style degeneracy (units = architecture layers) and
  pkg-style emptiness are pre-checked against the actual landing file sets;
  when the business capability lives in class-name prefixes, the ``camel``
  vocabulary is measured and recommended.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict

from .features import list_merges
from .modules import (STEREOTYPES, apply_unit_style, detect_scheme,
                      is_source, is_test_module, unit_of)

# ----------------------------------------------------------------- parsing --

R_CODEUP = re.compile(r"^Merge #(\d+) into (\S+) from (\S+)$")
R_GITHUB = re.compile(r"^Merge pull request #(\d+) from (\S+?)(?: into (\S+))?$")
R_SYNC = re.compile(r"^Merge remote-tracking branch '([^']+)' into (\S+)")
R_GITLAB_Q = re.compile(r"^Merge branch '([^']+)'(?: of \S+)? into '?([^'\s]+)'?")
R_PLAIN_INTO = re.compile(r"^Merge (?:branch )?'?([^'\s]+)'?(?: of \S+)? into '?([^'\s]+)'?")
R_NOINTO = re.compile(r"^Merge branch '([^']+)'$")


def parse_subject(subject: str) -> dict:
    """Structural parse of a merge subject -> style/source/target/mr.

    ``target=None`` means "into the branch that was checked out" (unknowable
    from the subject alone); callers treat it as the HEAD line.
    """
    s = (subject or "").strip()
    if m := R_CODEUP.search(s):
        return {"style": "codeup", "mr": m.group(1), "target": m.group(2),
                "source": m.group(3)}
    if m := R_GITHUB.search(s):
        return {"style": "github", "mr": m.group(1), "target": m.group(3),
                "source": m.group(2)}
    if m := R_SYNC.search(s):
        return {"style": "sync", "mr": None, "target": m.group(2),
                "source": m.group(1)}
    if m := R_GITLAB_Q.search(s):
        return {"style": "gitlab", "mr": None, "target": m.group(2),
                "source": m.group(1)}
    if m := R_PLAIN_INTO.search(s):
        return {"style": "plain", "mr": None, "target": m.group(2),
                "source": m.group(1)}
    if m := R_NOINTO.search(s):
        return {"style": "plain", "mr": None, "target": None,
                "source": m.group(1)}
    return {"style": "unknown", "mr": None, "target": None, "source": None}


# --------------------------------------------------------------- dialect ----

def _digit_runs(token: str) -> list[str]:
    return re.findall(r"\d+", token or "")


def discover_dialect(parsed: list[dict], min_support: int = 3) -> list[dict]:
    """Rank story-key regex candidates from source-branch digit runs.

    A shape (length + 2-digit prefix) is contaminated when the same shape
    recurs inside *line* target names (release/train numbers) — those are
    excluded so ``release-250903`` never becomes a story dialect.
    """
    src_shapes: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for p in parsed:
        if not p["source"]:
            continue
        for run in _digit_runs(p["source"]):
            if len(run) < 4:
                continue
            shape = f"{len(run)}:{run[:2]}"
            src_shapes[shape] += 1
            if run not in examples[shape]:
                examples[shape].append(run)
    if not src_shapes:
        return []
    # Line-name contamination per shape: digit runs inside *line* target
    # names (release trains, deploy ids). A target token that itself appears
    # as some merge's source (a feature branch that landed later) carries
    # the dialect, not line numbering, and is not contamination evidence.
    all_sources = {p["source"] for p in parsed if p["source"]}
    contam: Counter = Counter()
    for p in parsed:
        if not p["target"] or p["target"] in all_sources:
            continue
        for run in _digit_runs(p["target"]):
            if len(run) < 4:
                continue
            shape = f"{len(run)}:{run[:2]}"
            contam[shape] += 1
    out = []
    for shape, n in src_shapes.most_common():
        if n < min_support:
            continue
        if contam.get(shape, 0) > 0.3 * n:
            continue  # shape lives in line names, not story ids
        length, prefix = shape.split(":")
        runs = examples[shape]
        pin = sum(1 for r in runs if r.startswith(prefix)) / len(runs) >= 0.9
        pat = (re.escape(prefix) + r"\d{%d}" % (int(length) - len(prefix))) \
            if pin else r"\d{%d}" % int(length)
        out.append({"shape": shape, "regex": r"\b(" + pat + r")\b",
                    "support": n, "examples": runs[:3]})
    return out


# ------------------------------------------------------------ classification

def classify(parsed: list[dict], dialect: re.Pattern | None,
             head_line: str) -> list[dict]:
    """Role per merge: landing / review_iterations / sync / feature_internal /
    line_rollup / unknown.

    Lines are discovered data-driven: targets that receive story-keyed
    sources and do not carry a story key themselves (plus the HEAD line).
    ``refs/changes`` sources onto a *line* are MR landings (review patchset
    merged through to a line); onto a keyed branch they are review
    iterations. Rollup labeling additionally accepts line-like source names
    (release/hotfix/master/develop) the story flow never touched directly.
    """
    keyed_source = lambda t: bool(dialect and t and dialect.search(t))
    line_like = re.compile(r"^(release[-/]|hotfix[-/]|master$|develop$|main$)")
    line_like_feature = re.compile(r"^(feature[-/]|feat[-/]|lwh[-/])")
    lines = {head_line} if head_line else set()
    for p in parsed:
        if keyed_source(p["source"]) and not keyed_source(p["target"]):
            lines.add(p["target"])
    rows = []
    for p in parsed:
        src, tgt = p["source"], p["target"] or head_line
        if src and src.startswith("refs/changes"):
            role = "landing" if (tgt in lines and not keyed_source(tgt)) \
                else "review_iteration"
        elif p["style"] == "sync":
            role = "sync"
        elif keyed_source(tgt) or (tgt and line_like_feature.search(tgt)):
            role = "feature_internal"
        elif tgt in lines and keyed_source(src):
            role = "landing"
        elif tgt in lines and (src in lines or
                               (src and line_like.search(src))):
            role = "line_rollup"
        else:
            role = "landing" if tgt in lines else "unknown"
        rows.append({**p, "target": tgt, "role": role})
    return rows


# --------------------------------------------------------------- git helpers

def _git(path: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", path, *args], capture_output=True,
                          text=True)


def _diff_files(path: str, sha: str) -> list[str]:
    p = _git(path, "-c", "diff.renames=false", "diff", "--name-only",
             sha + "^", sha)
    return [f for f in p.stdout.splitlines() if f.strip()]


def _head_line(path: str) -> str | None:
    p = _git(path, "symbolic-ref", "--short", "HEAD")
    return p.stdout.strip() if p.returncode == 0 else "HEAD"


# ------------------------------------------------------------- unit precheck

LAYER_HINTS = STEREOTYPES | {"common", "rpc", "web", "core", "infra",
                             "infrastructure", "adapter", "application",
                             "domain", "facade", "client", "server",
                             "req", "reqs", "resp", "res", "entry",
                             "start", "boot"}


def _modules_are_layer_dirs(mod_units: set[str]) -> bool:
    """DDD monorepo test: module dirs = business prefix + layer suffix
    (billing-domain, billing-application, ...)."""
    toks = [re.split(r"[-_.]", m) for m in mod_units]
    common = 0
    for segs in zip(*toks):
        if len(set(segs)) == 1:
            common += 1
        else:
            break
    tails = ["-".join(t[common:]) for t in toks]
    if not any(tails):
        return False
    share = sum(1 for t in tails if t in LAYER_HINTS) / len(tails)
    return share >= 0.7


def unit_precheck(files_by_story: dict[str, list[str]],
                  all_files: list[str]) -> dict:
    """Degeneracy pre-check for module/pkg styles; camel vocabulary."""
    scheme = detect_scheme(all_files) if all_files else {"type": "flat2"}
    res = {"scheme": scheme["type"], "recommendation": None, "detail": {}}
    if not files_by_story:
        return res
    if scheme["type"] == "front":
        res["recommendation"] = "front (auto; page units)"
        return res
    # module-style base rate (the scatter label calibrate would train on)
    scatter = sum(1 for fs in files_by_story.values()
                  if len({u for u in (unit_of(scheme, f) for f in fs
                                      if is_source(f) and not is_test_module(f))
                          if u}) >= 3)
    base_rate = scatter / len(files_by_story)
    res["detail"]["module_scatter_base_rate"] = round(base_rate, 2)
    # are the module-style units just architecture layers?
    mod_units = {u for f in all_files
                 if is_source(f) and not is_test_module(f)
                 and (u := unit_of(scheme, f))}
    stereo = sum(1 for u in mod_units if u.lower() in LAYER_HINTS) \
        / max(len(mod_units), 1)
    layers = len(mod_units) >= 2 and (
        stereo >= 0.7 or _modules_are_layer_dirs(mod_units))
    res["detail"]["module_units_are_layers"] = layers
    # pkg simulation — viable only if its units are business segments, not
    # another layer of technical pseudo-units (common/, req/, resp/...)
    pkg_scheme = apply_unit_style(dict(scheme), all_files, "pkg")
    pkg_vocab = Counter(u for f in all_files
                        if is_source(f) and (u := unit_of(pkg_scheme, f)))
    pkg_units = set(pkg_vocab)
    pkg_stereo = (sum(c for u, c in pkg_vocab.items()
                      if u.lower() in LAYER_HINTS)
                  / max(sum(pkg_vocab.values()), 1))
    pkg_viable = len(pkg_units) >= 3 and pkg_stereo < 0.7
    res["detail"]["pkg_units"] = len(pkg_units)
    res["detail"]["pkg_technical_share"] = round(pkg_stereo, 2)
    # camel vocabulary (java files only by construction)
    camel_scheme = apply_unit_style(dict(scheme), all_files, "camel")
    vocab = Counter(u for f in all_files if is_source(f)
                    and (u := unit_of(camel_scheme, f)))
    java = sum(1 for f in all_files if f.endswith(".java"))
    recurring = {w: c for w, c in vocab.items() if c >= 2}
    res["detail"]["camel_top"] = vocab.most_common(8)
    camel_ok = len(recurring) >= 3 and java and sum(vocab.values()) >= 0.5 * java
    if layers and not pkg_viable and camel_ok:
        res["recommendation"] = "camel (module units are layers; pkg technical)"
    elif layers and pkg_viable:
        res["recommendation"] = "pkg (module units are layers; business packages)"
    elif base_rate >= 0.90 and pkg_viable:
        res["recommendation"] = "pkg (module scatter base rate degenerate)"
    else:
        res["recommendation"] = "module (default)"
    return res


# -------------------------------------------------------------------- probe --

def probe(path: str, since: str | None = None) -> dict:
    """One repository, one read-only pass. Returns the full report dict."""
    merges = list_merges(path, since, mainline=False)   # oldest first
    fp_subjects = {m["subject"] for m in
                   list_merges(path, since, mainline=True)}
    head_line = _head_line(path)
    parsed = [parse_subject(m["subject"]) for m in merges]
    dialects = discover_dialect(parsed)
    dialect = dialects[0] if dialects else None
    rx = re.compile(dialect["regex"]) if dialect else None
    rows = classify(parsed, rx, head_line)

    roles = Counter(r["role"] for r in rows)
    landing = [m for m, r in zip(merges, rows) if r["role"] == "landing"]
    keyed = [m for m, r in zip(merges, rows)
             if r["role"] == "landing" and rx and rx.search(m["subject"])]
    nested_shas = [m["sha"] for m, r in zip(merges, rows)
                   if r["role"] in ("review_iteration", "sync",
                                    "feature_internal")]

    # story-keyed landing lines + levels
    landing_lines = sorted({r["target"] for r in rows if r["role"] == "landing"})
    story_lines = sorted({r["target"] for m, r in zip(merges, rows)
                          if r["role"] == "landing" and rx and rx.search(m["subject"])})
    off_head = [ln for ln in story_lines if ln != head_line]
    levels = "direct" if not off_head else \
        ("two_level" if len(story_lines) <= 6 else "two_level_multi_train")
    on_fp = sum(1 for m in keyed if m["subject"] in fp_subjects)
    ff_mix = bool(keyed) and 0.2 * len(keyed) < on_fp < 0.8 * len(keyed)

    # multi-line inheritance: how many landing lines' first-parent chains
    # contain each keyed landing (per-line worktrees would double-count)
    inheritance = {"median": 1, "max": 1}
    containment: dict[str, int] = defaultdict(int)
    keyed_set = {m["sha"] for m in keyed}
    line_refs = [ln for ln in landing_lines if ln and ln != "HEAD"]
    for ln in line_refs[:120]:
        ref = ln if ln.startswith("HEAD") else \
            (ln if _git(path, "rev-parse", "--verify", "--quiet",
                        ln).returncode == 0
             else "origin/" + ln)
        if _git(path, "rev-parse", "--verify", "--quiet", ref).returncode != 0:
            continue
        p = _git(path, "rev-list", "--first-parent", ref)
        for sha in p.stdout.split():
            if sha in keyed_set:
                containment[sha] += 1
    if keyed_set:
        counts = sorted(containment.get(s, 0) or 1 for s in keyed_set)
        inheritance = {"median": counts[len(counts) // 2],
                       "max": counts[-1]}

    # squash / linear-history coverage check
    n_commits = int(_git(path, "rev-list", "--count", "HEAD").stdout or 0)
    merge_ratio = len(merges) / n_commits if n_commits else 1.0
    squash = {"merge_ratio": round(merge_ratio, 4), "covered": True,
              "note": None}
    if len(merges) < 5 and n_commits > 200:
        squash = {"merge_ratio": round(merge_ratio, 4), "covered": False,
                  "note": "near-empty --merges log: squash/linear workflow, "
                          "not covered by this instrument"}

    # unit precheck over the file universe init will actually replay:
    # landings + line rollups (rollups carry no keys but deepen the common
    # package prefix, which is exactly what init's scheme detection sees)
    replay = [m for m, r in zip(merges, rows)
              if r["role"] in ("landing", "line_rollup")]
    files_by_story: dict[str, list[str]] = defaultdict(list)
    all_files: list[str] = []
    for m in replay[:300]:
        files = _diff_files(path, m["sha"])
        all_files.extend(files)
        if rx and (k := rx.search(m["subject"])):
            files_by_story[k.group(1)].extend(files)
    unit = unit_precheck(files_by_story, all_files)

    # mainline=true is sufficient when every keyed landing is reachable on
    # HEAD's own first-parent chain (nested merges are then invisible by
    # design); otherwise stage a clone and use mainline=false.
    mainline_rec = (levels == "direct" and not ff_mix
                    and inheritance["median"] <= 1 and inheritance["max"] <= 1)
    warnings = []
    if _git(path, "config", "--get", "diff.renames").stdout.strip() == "true":
        warnings.append("diff.renames=true: rename detection fetches blobs "
                        "on partial clones and hangs; set it false")
    if dialect and len(keyed) < 0.4 * len(landing):
        warnings.append(f"dialect keys {len(keyed)}/{len(landing)} landings; "
                        "if ids live in message bodies, extract them from "
                        "branch names instead (feature_key reads subjects)")
    if nested_shas:
        if mainline_rec:
            warnings.append(f"{len(nested_shas)} nested merges (review/sync/"
                            "feature-internal) present; invisible under "
                            "mainline=true (no action needed)")
        else:
            warnings.append(f"{len(nested_shas)} nested merges (review/sync/"
                            "feature-internal) would pollute feature tables; "
                            "stage a grafted clone before init (see toml recipe)")
    if inheritance["median"] >= 2:
        warnings.append(f"keyed landings sit on median {inheritance['median']} "
                        "lines' first-parent chains: per-line worktrees "
                        "double-count; use mainline=false on a staged clone")
    elif inheritance["max"] >= 5:
        warnings.append(f"some keyed landings sit on up to {inheritance['max']} "
                        "lines' first-parent chains (fast-forward rollups): "
                        "per-line worktrees double-count them")

    return {
        "repo": path, "head_line": head_line, "since": since,
        "workflow": {"levels": levels, "landing_lines": landing_lines,
                     "story_lines": story_lines, "ff_mixed_era": ff_mix},
        "merges": {"total": len(merges),
                   "landing": roles.get("landing", 0),
                   "line_rollup": roles.get("line_rollup", 0),
                   "keyed": len(keyed), "keyed_on_head_fp": on_fp,
                   "nested": {"review_iteration": roles.get("review_iteration", 0),
                              "sync": roles.get("sync", 0),
                              "feature_internal": roles.get("feature_internal", 0)}},
        "dialect": dialect or {"regex": None, "support": 0, "examples": []},
        "dialect_coverage": (round(len(keyed) / len(landing), 2)
                             if landing else 0.0),
        "dialect_candidates": dialects,
        "inheritance": inheritance,
        "squash": squash,
        "unit_style": unit,
        "recommended": {"mainline": mainline_rec,
                        "unit_style": unit["recommendation"],
                        "regex": dialect["regex"] if dialect else None},
        "staging": {"grafts": nested_shas},
        "warnings": warnings,
    }


# ------------------------------------------------------------------ render --

def render(r: dict) -> str:
    w, m, u = r["workflow"], r["merges"], r["unit_style"]
    L = [f"repo: {r['repo']}  head: {r['head_line']}",
         f"workflow: {w['levels']}"
         + ("  [mixed fast-forward era]" if w["ff_mixed_era"] else ""),
         f"landing lines ({len(w['landing_lines'])}): "
         + ", ".join(w["landing_lines"][:12])
         + (" ..." if len(w["landing_lines"]) > 12 else ""),
         f"merges: {m['total']} total = {m['landing']} landing "
         f"({m['keyed']} keyed, {m['keyed_on_head_fp']} on head first-parent) "
         f"+ {m['line_rollup']} line-rollup + "
         f"{sum(m['nested'].values())} nested {tuple(m['nested'].values())}"
         " (review,sync,feat-int)"]
    d = r["dialect"]
    L.append(f"dialect: {d['regex']}  support={d['support']} "
             f"examples={d['examples']}" if d["regex"]
             else "dialect: none found (merges stay statistics-only)")
    L.append(f"inheritance: keyed landings on median {r['inheritance']['median']} "
             f"(max {r['inheritance']['max']}) lines' first-parent chains")
    if not r["squash"]["covered"]:
        L.append(f"squash: NOT COVERED ({r['squash']['note']})")
    det = u["detail"]
    if det:
        L.append(f"unit style: scheme={u['scheme']} "
                 f"module_base_rate={det.get('module_scatter_base_rate')} "
                 f"pkg_units={det.get('pkg_units')} -> {u['recommendation']}")
        if det.get("camel_top"):
            L.append("  camel vocab: "
                     + ", ".join(f"{w_}x{c}" for w_, c in det["camel_top"][:8]))
    else:
        L.append(f"unit style: scheme={u['scheme']} -> {u['recommendation']}")
    L.append(f"recommended: mainline={r['recommended']['mainline']}  "
             f"unit_style={(u['recommendation'] or 'module').split(' ')[0]}  "
             f"regex={r['recommended']['regex']}")
    for wn in r["warnings"]:
        L.append(f"warning: {wn}")
    return "\n".join(L)


def toml_scaffold(r: dict) -> str:
    rec = r["recommended"]
    lines = ["# uscm.toml scaffold generated by `uscm probe` — review first."]
    if not rec["mainline"]:
        lines += [
            "# two-level landing flow with nested merges / multi-line inheritance:",
            "# stage a grafted clone first, then point repos at it.",
            "#   git clone --shared <this-repo> <this-repo>-analysis",
            "#   cd <this-repo>-analysis && git config diff.renames false",
            f"#   git replace --graft <sha>  # x{len(r['staging']['grafts'])}, "
            "full list: uscm probe <repo> --json -> .staging.grafts",
            "mainline = false",
            'repos = ["<path-to-staged-clone>"]',
        ]
    else:
        lines += ["mainline = true", 'repos = ["<repo-path>"]']
    style = (rec["unit_style"] or "module").split(" ")[0]
    if style != "module":
        lines.append(f'unit_style = "{style}"')
    if rec["regex"] and r.get("dialect_coverage", 1.0) >= 0.2:
        lines += ["", "[[feature]]",
                  f'regex = "{rec["regex"].replace(chr(92), chr(92) * 2)}"',
                  'tag = "S{0}"']
    elif rec["regex"]:
        lines += ["", "# dialect coverage too low to trust; no [[feature]] "
                  "emitted — merges stay statistics-only"]
    return "\n".join(lines) + "\n"
