"""Merge-history extraction: git merges -> feature units.

A *feature* is identified by a key extracted from the merge-commit subject
(configurable regex list, ``uscm.toml``), or - for merges whose subject
carries none - from the merged paths (``where = "path"`` patterns; e.g. a
per-story deploy archive). Merges without a feature key still update
repository statistics but produce no feature-level verdicts.
"""
from __future__ import annotations

import re
import subprocess

DEFAULT_PATTERNS: list[tuple] = [
    # (regex, tag template[, where]; first match wins)
    # where = "subject" (default): matched against the merge subject
    # where = "path": matched against each merged file path
    (r"(?:--story=|story[/:]\s*)(\d{3,})", "S{0}"),
    (r"\b([A-Z][A-Z0-9_]{1,9}-\d{2,})\b", "{0}"),      # JIRA-like keys
    (r"TAPD[ #]?(\d{5,})", "S{0}"),
]


def git(repo_path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo_path), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def compile_patterns(patterns: list[tuple] | None):
    pats = patterns or DEFAULT_PATTERNS
    out = []
    for pat in pats:
        where = pat[2] if len(pat) > 2 else "subject"
        out.append((re.compile(pat[0]), pat[1], where))
    return out


def _tagged(m, tag: str) -> str:
    try:
        return tag.format(m.group(1))
    except (IndexError, KeyError):
        return m.group(1)


def feature_key(subject: str, compiled=None) -> str | None:
    """Feature key from a merge subject, or None."""
    for rx, tag, where in (compiled or compile_patterns(None)):
        if where == "path":
            continue
        m = rx.search(subject or "")
        if m:
            return _tagged(m, tag)
    return None


def path_keys(files: list[str], compiled=None) -> dict[str, int]:
    """Feature keys carried by merged paths -> {key: paths carrying it}."""
    counts: dict[str, int] = {}
    for f in files:
        for rx, tag, where in (compiled or compile_patterns(None)):
            if where != "path":
                continue
            m = rx.search(f)
            if m:
                k = _tagged(m, tag)
                counts[k] = counts.get(k, 0) + 1
                break                      # first matching pattern per path
    return counts


def merge_key(subject: str, files: list[str], compiled=None) -> dict:
    """Feature attribution of one merge: ``{key, key_source, path_keys}``.

    The subject decides when it carries a key (the authorial branch name).
    Otherwise the paths may: a repository that archives deployments per
    story (``deploy/2026/Q4/20261105@1000002/...``) keys the merges whose
    subjects are bare. A merge bundling several stories' paths is
    attributed to the story with the most paths - one merge, one feature -
    and the others stay visible in ``path_keys``. Everything read here is
    part of the merge itself, so the attribution is still pre-event.
    """
    compiled = compile_patterns(compiled)
    k = feature_key(subject, compiled)
    if k:
        return {"key": k, "key_source": "subject", "path_keys": {}}
    counts = path_keys(files, compiled)
    if not counts:
        return {"key": None, "key_source": None, "path_keys": {}}
    key = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {"key": key, "key_source": "path", "path_keys": counts}


def list_merges(repo_path, since: str | None = None,
                mainline: bool = True) -> list[dict]:
    """Merge commits, oldest first. Each: {sha, date, subject}.

    ``mainline=True`` (default) walks the first-parent chain only: the unit
    of change is a merge *onto the mainline* (one merged request), which also
    ignores nested merges inside feature branches.
    """
    args = ["log", "--merges"]
    if mainline:
        args.append("--first-parent")
    args += ["--date=iso-strict", "--format=%H%x09%ad%x09%s"]
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


def merges_after(repo_path, head: str, since: str | None = None,
                 mainline: bool = True) -> list[dict]:
    """Merges reachable from HEAD or FETCH_HEAD but not from ``head``.

    Union of both refs so a bare ``git fetch`` (no local pull) is still seen;
    already-processed merges are filtered by the caller via its registry.
    """
    seen: dict[str, dict] = {}
    for ref in ("HEAD", "FETCH_HEAD"):
        args = ["log", "--merges"]
        if mainline:
            args.append("--first-parent")
        args += ["--date=iso-strict", "--format=%H%x09%ad%x09%s",
                 f"{head}..{ref}"]
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
    """Files brought in by a merge (first-parent diff).

    NUL-separated and unquoted, so non-ASCII paths arrive verbatim. Rename
    detection is off: it fetches blobs on partial clones and changes no
    path in a ``--name-only`` diff.
    """
    p = git(repo_path, "-c", "diff.renames=false", "diff", "--name-only",
            "-z", sha + "^", sha)
    return [f for f in p.stdout.split("\0") if f.strip()]


def merge_author(repo_path, sha: str) -> str | None:
    """Most frequent committer inside the merged branch; else merge author.

    Ties go to the lexicographically first name: a plain ``set`` iterates
    in hash order, which made attribution (and every coefficient built on
    KA/GA) depend on the process hash seed.
    """
    p = git(repo_path, "log", "--format=%an", f"{sha}^1..{sha}^2")
    names = [x for x in p.stdout.splitlines() if x.strip()]
    if names:
        return max(sorted(set(names)), key=names.count)
    q = git(repo_path, "log", "-1", "--format=%an", sha)
    return q.stdout.strip() or None


def head_of(repo_path) -> str | None:
    p = git(repo_path, "rev-parse", "HEAD")
    return p.stdout.strip() if p.returncode == 0 else None
