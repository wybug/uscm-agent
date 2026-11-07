"""Merge-history extraction: git merges -> feature units.

A *feature* is identified by a key extracted from the merge-commit subject
(configurable regex list, ``uscm.toml``). Merges without a feature key still
update repository statistics but produce no feature-level verdicts.
"""
from __future__ import annotations

import re
import subprocess

DEFAULT_PATTERNS: list[tuple[str, str]] = [
    # (regex on merge subject, tag template; first match wins)
    (r"(?:--story=|story[/:]\s*)(\d{3,})", "S{0}"),
    (r"\b([A-Z][A-Z0-9_]{1,9}-\d{2,})\b", "{0}"),      # JIRA-like keys
    (r"TAPD[ #]?(\d{5,})", "S{0}"),
]


def git(repo_path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_path), *args],
                          capture_output=True, text=True)


def compile_patterns(patterns: list[tuple[str, str]] | None):
    pats = patterns or DEFAULT_PATTERNS
    return [(re.compile(rx), tag) for rx, tag in pats]


def feature_key(subject: str, compiled=None) -> str | None:
    """Feature key from a merge subject, or None."""
    for rx, tag in (compiled or compile_patterns(None)):
        m = rx.search(subject or "")
        if m:
            try:
                return tag.format(m.group(1))
            except (IndexError, KeyError):
                return m.group(1)
    return None


def list_merges(repo_path, since: str | None = None) -> list[dict]:
    """All merge commits, oldest first. Each: {sha, date, subject}."""
    args = ["log", "--merges", "--date=iso-strict", "--format=%H%x09%ad%x09%s"]
    if since:
        args += ["--since", since]
    p = git(repo_path, *args)
    rows = []
    for line in p.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        rows.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
    rows.reverse()
    return rows


def merges_after(repo_path, head: str, since: str | None = None) -> list[dict]:
    """Merges reachable from HEAD or FETCH_HEAD but not from ``head``.

    Union of both refs so a bare ``git fetch`` (no local pull) is still seen;
    already-processed merges are filtered by the caller via its registry.
    """
    seen: dict[str, dict] = {}
    for ref in ("HEAD", "FETCH_HEAD"):
        args = ["log", "--merges", "--date=iso-strict",
                "--format=%H%x09%ad%x09%s", f"{head}..{ref}"]
        if since:
            args += ["--since", since]
        q = git(repo_path, *args)
        if q.returncode != 0:
            continue
        for line in q.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) == 3:
                seen.setdefault(parts[0], {"sha": parts[0], "date": parts[1],
                                           "subject": parts[2]})
    return sorted(seen.values(), key=lambda m: (m["date"], m["sha"]))


def merge_files(repo_path, sha: str) -> list[str]:
    """Files brought in by a merge (first-parent diff)."""
    p = git(repo_path, "diff", "--name-only", sha + "^", sha)
    return [f for f in p.stdout.splitlines() if f.strip()]


def merge_author(repo_path, sha: str) -> str | None:
    """Most frequent committer inside the merged branch; else merge author."""
    p = git(repo_path, "log", "--format=%an", f"{sha}^1..{sha}^2")
    names = [x for x in p.stdout.splitlines() if x.strip()]
    if names:
        return max(set(names), key=names.count)
    q = git(repo_path, "log", "-1", "--format=%an", sha)
    return q.stdout.strip() or None


def head_of(repo_path) -> str | None:
    p = git(repo_path, "rev-parse", "HEAD")
    return p.stdout.strip() if p.returncode == 0 else None
