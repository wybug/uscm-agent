"""Deterministic synthetic microservice-system generator.

Builds real git repositories (multi-module Java services, a shared commons
hub, Go services with flat directory modules, a front-end SPA) and drives
feature development through them with merge commits tagged ``--story=N``.

Scatter outcomes are planted from the regime law itself,

    logit P(scatter) = -1.0 + 0.9*log(nMR) - 0.6*GA,

so the full agent loop (init -> calibrate -> watch -> check -> advise ->
report) can be demonstrated and regression-tested end-to-end without any
private data: calibration is expected to recover the planted directions
(b1 > 0, b3 < 0). Output is fully determined by the seed.

Layout for the default 8 repositories:
    svc-order, svc-pay, svc-user, svc-promo   Java multi-module (core/api/web)
    platform-common                           shared hub (util/domain)
    gateway, jobs                             Go flat2
    portal-web                                front-end (pages/api/comp)
"""
from __future__ import annotations

import json
import math
import os
import random
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PLANTED = {"intercept": -1.0, "log_nMR": 0.9, "KA": 0.0, "GA": -0.6}
AUTHORS = ["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Gina", "Hank"]
BASE = datetime(2025, 1, 6, 10, 0, 0, tzinfo=timezone.utc)


def topology(n_repos: int) -> dict[str, dict]:
    repos: dict[str, dict] = {}
    n_java = max(1, n_repos - 4)
    domains = ["order", "pay", "user", "promo", "stock", "risk", "msg",
               "contract", "settle", "ticket"]
    for d in domains[:n_java]:
        repos[f"svc-{d}"] = {"kind": "java",
                             "units": ["core", "api", "web"],
                             "file": lambda u, k: f"{u}/src/main/java/com/x/"
                                                  f"{u}/F{k}.java"}
    repos["platform-common"] = {"kind": "java", "units": ["util", "domain"],
                                "file": lambda u, k: f"{u}/src/main/java/com/x/"
                                                     f"{u}/F{k}.java"}
    repos["gateway"] = {"kind": "go",
                        "units": ["cmd/server", "internal/auth",
                                  "internal/router"],
                        "file": lambda u, k: f"{u}/f{k}.go"}
    repos["jobs"] = {"kind": "go",
                     "units": ["tasks/cleanup", "tasks/report", "internal/queue"],
                     "file": lambda u, k: f"{u}/f{k}.go"}
    repos["portal-web"] = {"kind": "front",
                           "units": ["page:orders", "page:profile",
                                     "page:promo", "page:admin"],
                           "file": lambda u, k: f"src/views/{u[5:]}/F{k}.tsx"}
    return repos


def _git(repo: Path, *args, env=None):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr.strip()}")
    return r


def _mk(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Synth")
    _git(repo, "config", "user.email", "s@example.com")
    (repo / "README.md").write_text("# synthetic repo\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "chore: bootstrap",
         env=_env(BASE, "Synth"))


def _env(when: datetime, author: str) -> dict:
    return {**os.environ,
            "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": "s@example.com",
            "GIT_COMMITTER_NAME": "Synth", "GIT_COMMITTER_EMAIL": "s@example.com",
            "GIT_AUTHOR_DATE": when.isoformat(),
            "GIT_COMMITTER_DATE": when.isoformat()}


def _merge(repo: Path, key: str, num: int, when: datetime, author: str,
           writes: list[str]):
    env = _env(when, author)
    branch = f"b-{key}-{num}"
    _git(repo, "checkout", "-q", "-b", branch, env=env)
    for path in writes:
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        old = f.read_text() if f.exists() else ""
        f.write_text(old + f"// change {key} r{num}\n")
        _git(repo, "add", path, env=env)
    _git(repo, "commit", "-q", "-m", f"wip {key}", env=env)
    _git(repo, "checkout", "-q", "main", env=env)
    _git(repo, "merge", "--no-ff", "-q", branch, "-m",
         f"Merge {key} into main from feature/{key} (--story={num:06d})",
         env=env)
    _git(repo, "branch", "-q", "-D", branch, env=env)


def generate(out_dir: str, seed: int = 7, n_repos: int = 8,
             n_features: int = 60, months: int = 18) -> dict:
    rng = random.Random(seed)
    out = Path(out_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} exists and is not empty")
    repos = topology(n_repos)
    for name in repos:
        _mk(out / name)

    java_backends = [n for n, r in repos.items()
                     if r["kind"] == "java" and n != "platform-common"]
    hub = repos["platform-common"]
    front = repos.get("portal-web")

    features = []
    events = []  # (when, repo, key, num, author, unit)
    for i in range(n_features):
        key = f"S{i:06d}"
        nmr = max(2, min(2 + int(rng.expovariate(0.35)), 12))
        n_team = rng.choices([1, 2, 3], weights=[0.5, 0.35, 0.15])[0]
        team = rng.sample(AUTHORS, n_team)
        weights = [0.2 + rng.random() for _ in team]

        def pick_author():
            return rng.choices(team, weights)[0]

        home = rng.choice(java_backends)
        home_units = rng.sample(repos[home]["units"], k=min(2, len(repos[home]["units"])))
        # scatter outcome drawn once per feature (planted law)
        # GA/kA realized from MR author draws; law uses them
        draws = [pick_author() for _ in range(nmr)]
        counts = {a: draws.count(a) for a in set(draws)}
        ka = len(counts)
        pa = [c / nmr for c in counts.values()]
        ent = -sum(p * math.log(p) for p in pa)
        ga = 1.0 if ka == 1 else 1 - ent / math.log(ka)
        z = (PLANTED["intercept"] + PLANTED["log_nMR"] * math.log(nmr)
             + PLANTED["KA"] * ka + PLANTED["GA"] * ga)
        p_scatter = 1 / (1 + math.exp(-z))
        scattered = rng.random() < p_scatter

        target_units: list[tuple[str, str]] = []  # (repo, unit)
        for u in home_units:
            target_units.append((home, u))
        if scattered:
            k_extra = rng.randint(1, 5)
            for _ in range(k_extra):
                r = rng.random()
                if r < 0.35:
                    target_units.append(("platform-common", rng.choice(hub["units"])))
                elif r < 0.85:
                    others = [b for b in java_backends if b != home]
                    if others:
                        other = rng.choice(others)
                        target_units.append((other, rng.choice(repos[other]["units"])))
                elif front:
                    target_units.append(("portal-web", rng.choice(front["units"])))
            rng.shuffle(target_units)
        target_units = list(dict.fromkeys(target_units))  # dedupe, keep order

        start = BASE + timedelta(days=rng.randint(0, 30 * (months - 2)))
        t = start
        seen: list[tuple[str, str]] = []
        for j in range(nmr):
            if j == 0:
                batch = target_units[:rng.randint(1, min(2, len(target_units)))]
            elif scattered and seen and rng.random() < 0.6 and len(seen) < len(target_units):
                more = [u for u in target_units if u not in seen]
                batch = more[:rng.randint(1, min(2, len(more)))]
            else:
                batch = [rng.choice(seen)] if seen else target_units[:1]
            for u in batch:
                if u not in seen:
                    seen.append(u)
            for repo_name, unit in batch:
                events.append((t, repo_name, key, i, draws[j], unit))
            t += timedelta(weeks=rng.randint(1, 5))
        features.append({"key": key, "nMR": nmr, "units": [f"{r}:{u}" for r, u in seen],
                         "scatter": scattered, "KA": ka, "GA": round(ga, 3)})
    events.sort(key=lambda e: e[0])

    merges = 0
    for when, repo_name, key, num, author, unit in events:
        spec = repos[repo_name]
        path = spec["file"](unit, num)
        if spec["kind"] == "front" and rng.random() < 0.5:
            # accompany with a normative layer crossing (api/comp), no new unit
            side = rng.choice(["api/order.ts", "components/Btn.tsx"])
            _merge(out / repo_name, key, num, when, author, [path, f"src/{side}"])
        else:
            _merge(out / repo_name, key, num, when, author, [path])
        merges += 1

    manifest = {"seed": seed, "planted_law": PLANTED,
                "repos": {n: r["kind"] for n, r in repos.items()},
                "features": features, "merges": merges,
                "scatter_rate": round(sum(f["scatter"] for f in features)
                                      / len(features), 3)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest
