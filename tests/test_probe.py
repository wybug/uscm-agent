"""Tests for the workflow pre-analysis (``uscm probe``)."""
import os
import subprocess

import pytest

from uscm.probe import (classify, discover_dialect, parse_subject, probe,
                        toml_scaffold)


# ------------------------------------------------------------ parse_subject --

def test_parse_subject_styles():
    codeup = parse_subject("Merge #95 into release-26-21 from feature/26-19/1093983")
    assert codeup == {"style": "codeup", "mr": "95", "target": "release-26-21",
                      "source": "feature/26-19/1093983"}
    gh = parse_subject("Merge pull request #42 from wybug/uscm-agent/feat")
    assert gh["style"] == "github" and gh["source"].startswith("wybug/") \
        and gh["target"] is None
    sync = parse_subject("Merge remote-tracking branch 'origin/develop' "
                         "into feature-1049186")
    assert sync["style"] == "sync" and sync["target"] == "feature-1049186"
    gl = parse_subject("Merge branch 'feature/1049186-fix' into develop")
    assert gl["style"] == "gitlab" and gl["target"] == "develop"
    gl2 = parse_subject("Merge branch 'master' of codeup.x.com:g/r into feature-dump")
    assert gl2["style"] == "gitlab" and gl2["target"] == "feature-dump" \
        and gl2["source"] == "master"
    plain = parse_subject("Merge release-26-22 into master")
    assert plain["style"] == "plain" and plain["source"] == "release-26-22" \
        and plain["target"] == "master"
    nointo = parse_subject("Merge branch 'feature-1049186'")
    assert nointo["style"] == "plain" and nointo["target"] is None
    assert parse_subject("Revert \"x\"")["style"] == "unknown"


# ---------------------------------------------------------- discover_dialect --

def _p(src, tgt=None):
    return {"style": "codeup", "mr": "1", "source": src, "target": tgt}


def test_dialect_pins_prefix_and_support():
    parsed = [_p(f"feature-{i}") for i in
              (1049186, 1051258, 1063584, 1076837)]
    d = discover_dialect(parsed)
    assert d and d[0]["regex"] == r"\b(10\d{5})\b"
    assert d[0]["support"] == 4


def test_dialect_excludes_line_name_shapes():
    # shape (7:42) has source support but recurs inside release-train
    # target names that never appear as sources -> contamination, excluded.
    parsed = [_p("task-4245663-fix1", "release-4245663-9"),
              _p("task-4245663-fix2", "release-4245663-9"),
              _p("task-4245663-fix3", "release-4245663-9")]
    assert discover_dialect(parsed) == []
    # feature-branch targets carrying ids are NOT contamination: the same
    # token appears as a source elsewhere (it landed later).
    parsed = [
        _p("feature-1060297-shop-point-2", "release-26-12"),
        {"style": "codeup", "mr": "67", "source": "refs/changes/67/head",
         "target": "feature-1060297-shop-point-2"},
        _p("feature-1063584-transfer-risk", "release-26-12"),
        _p("feature-1064565", "release-26-12"),
    ]
    d = discover_dialect(parsed)
    assert d and d[0]["regex"] == r"\b(10\d{5})\b"


def test_dialect_needs_min_support():
    parsed = [_p("feature-1049186"), _p("feature-x")]
    assert discover_dialect(parsed) == []


# ---------------------------------------------------------------- classify --

def test_classify_roles_and_lines():
    parsed = [
        _p("feature-1093983", "release-26-21"),                    # landing
        _p("refs/changes/67/head", "feature/cs/m-1083451"),        # review it.
        _p("refs/changes/61/head", "master"),                      # landing
        parse_subject("Merge remote-tracking branch 'origin/release-20250827'"
                      " into feature-1064565"),                    # sync
        _p("feature-1061590", "feature-1060297"),                  # feat-int
        {"style": "plain", "mr": None, "source": "release-26-22",
         "target": "master"},                                      # rollup
        {"style": "plain", "mr": None, "source": "release-2099",
         "target": "master"},                                      # rollup
    ]
    import re
    rows = classify(parsed, re.compile(r"\b10\d{5}\b"), "master")
    roles = [r["role"] for r in rows]
    assert roles == ["landing", "review_iteration", "landing", "sync",
                     "feature_internal", "line_rollup", "line_rollup"]
    lines = {r["target"] for r in rows if r["role"] == "landing"}
    assert "release-26-21" in lines and "master" in lines


# ------------------------------------------------------------------- e2e ----

def _git(repo, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "CI",
           "GIT_AUTHOR_EMAIL": "ci@e.com",
           "GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@e.com"}
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def _commit_file(repo, name, content="x"):
    import pathlib
    p = pathlib.Path(repo) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", f"wip {name}")


def test_probe_two_level_flow_with_nested(tmp_path):
    """codeup-style repo: feature -> develop landings, one feature branch
    carrying a refs/changes review iteration and a sync merge before it
    lands, develop rolled up to master."""
    repo = tmp_path / "svc"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "CI")
    _git(repo, "config", "user.email", "ci@e.com")
    _commit_file(repo, "README.md", "demo\n")
    _git(repo, "checkout", "-q", "-b", "develop")

    # two keyed landings onto develop (gitlab-style subjects)
    for sid in ("1049186", "1051258"):
        _git(repo, "checkout", "-q", "-b", f"feature-{sid}")
        _commit_file(repo, f"src/main/java/com/x/Svc{sid}.java",
                     f"package com.x; class Svc{sid} {{}}\n")
        _git(repo, "checkout", "-q", "develop")
        _git(repo, "merge", "--no-ff", "-q", f"feature-{sid}", "-m",
             f"Merge branch 'feature-{sid}' into develop")

    # a feature branch with a nested review iteration inside
    feat = "feature-1060297-shop-point-2"
    _git(repo, "checkout", "-q", "-b", feat)
    _commit_file(repo, "src/main/java/com/x/Point.java", "p\n")
    _git(repo, "checkout", "-q", "-b", "refs/changes/67/head")
    _commit_file(repo, "src/main/java/com/x/PointFix.java", "f\n")
    _git(repo, "checkout", "-q", feat)
    _git(repo, "merge", "--no-ff", "-q", "refs/changes/67/head", "-m",
         "Merge #67 into feature-1060297-shop-point-2 from refs/changes/67/head")

    # develop moves on, so the sync merge below has real content
    _git(repo, "checkout", "-q", "-b", "feature-1053075")
    _commit_file(repo, "src/main/java/com/x/Svc1053075.java", "class X {}\n")
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "merge", "--no-ff", "-q", "feature-1053075", "-m",
         "Merge branch 'feature-1053075' into develop")

    # nested sync merge on the feature branch, then land it
    _git(repo, "checkout", "-q", feat)
    _git(repo, "merge", "--no-ff", "-q", "develop", "-m",
         f"Merge remote-tracking branch 'origin/develop' into {feat}")
    _git(repo, "checkout", "-q", "develop")
    _git(repo, "merge", "--no-ff", "-q", feat, "-m",
         f"Merge branch '{feat}' into develop")

    # rollup develop -> master (real merge, so landings stay off master's fp)
    _git(repo, "checkout", "-q", "master")
    _git(repo, "merge", "--no-ff", "-q", "develop", "-m",
         "Merge branch 'develop'")

    r = probe(str(repo))
    assert r["workflow"]["levels"] in ("two_level", "two_level_multi_train")
    assert r["merges"]["landing"] == 4 and r["merges"]["keyed"] == 4
    assert r["merges"]["nested"]["review_iteration"] == 1
    assert r["merges"]["nested"]["sync"] == 1
    assert r["merges"]["line_rollup"] == 1
    assert r["dialect"]["regex"] == r"\b(10\d{5})\b"
    # nested pollution -> staged clone recommended
    assert r["recommended"]["mainline"] is False
    assert len(r["staging"]["grafts"]) == 2
    assert "mainline = false" in toml_scaffold(r)


def test_probe_direct_flow(tmp_path):
    """feature -> mainline directly, no nested merges: mainline=true."""
    from tests.conftest import init_repo, make_merge
    repo = init_repo(tmp_path / "direct")
    for n in (11, 12, 13):
        make_merge(repo, n, [f"src/main/java/com/x/A{n}.java"])
    r = probe(str(repo))
    assert r["workflow"]["levels"] == "direct"
    assert sum(r["merges"]["nested"].values()) == 0
    assert r["recommended"]["mainline"] is True
    assert "mainline = true" in toml_scaffold(r)
