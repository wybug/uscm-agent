"""Shared fixtures: tiny git repos with story-tagged merges."""
import os
import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args, env=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       text=True, env=env)
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r


def make_merge(repo: Path, story_num: int, files: list[str], author="Alice",
               date="2025-05-01T10:00:00+00:00"):
    """Branch-commit then --no-ff merge with a --story tagged subject."""
    env = {**os.environ,
           "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "a@e.com",
           "GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@e.com",
           "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    branch = f"b-{story_num}-{len(files)}-{abs(hash(tuple(files))) % 997}"
    git(repo, "checkout", "-q", "-b", branch, env=env)
    for f in files:
        p = repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text((p.read_text() if p.exists() else "") + "// touch\n")
        git(repo, "add", f, env=env)
    git(repo, "commit", "-q", "-m", f"wip {story_num}", env=env)
    git(repo, "checkout", "-q", "main", env=env)
    git(repo, "merge", "--no-ff", "-q", branch, "-m",
        f"Merge S{story_num:06d} into main from feature/f "
        f"(--story={story_num:06d})", env=env)
    git(repo, "branch", "-q", "-D", branch, env=env)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "CI")
    git(path, "config", "user.email", "ci@e.com")
    (path / "README.md").write_text("demo\n")
    git(path, "add", "README.md")
    git(path, "commit", "-q", "-m", "bootstrap")
    return path


@pytest.fixture
def tiny_repo(tmp_path):
    yield init_repo(tmp_path / "svc-demo")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """Empty workspace directory (cwd switched into it)."""
    w = tmp_path / "ws"
    w.mkdir()
    monkeypatch.chdir(w)
    yield w
