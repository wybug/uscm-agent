#!/usr/bin/env bash
# Full walkthrough of the uscm-agent decision loop on a synthetic
# microservice system. Run from anywhere; everything lands under demo/_work.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)
PY=${PY:-$ROOT/.venv/bin/python}
command -v git >/dev/null || { echo "git required"; exit 1; }

WORK=_work
rm -rf "$WORK"
mkdir -p "$WORK/ws"

echo "== 0. generate a deterministic synthetic system (8 repos, 60 features)"
"$PY" -m uscm.cli synth --out "$WORK/system" --seed 7 --repos 8 --features 60

cd "$WORK/ws"
USCM() { "$PY" -m uscm.cli "$@"; }

echo
echo "== 1. init: scan repos, replay history with the frozen pooled prior"
USCM init --repos "../system/*"

echo
echo "== 2. calibrate: local refit + tau + Phi budgets + self-checks"
USCM calibrate

echo
echo "== 3. advise: top scatter-risk features"
USCM advise --top 8

echo
echo "== 4. check: single-merge verdicts (read-only)"
echo "-- continue the highest-risk feature that has an untouched unit in svc-order..."
read -r STORY SHA UNIT < <("$PY" <<'EOF'
import json, subprocess
from pathlib import Path

rows = json.loads(subprocess.run(
    [__import__("sys").executable, "-m", "uscm.cli", "advise", "--top", "10",
     "--json"], capture_output=True, text=True).stdout)
st = json.loads((Path.cwd() / ".uscm/state.json").read_text())
repo = Path("../system/svc-order")
for row in rows:
    story = row["story"]
    used = set(st["features"][story]["units"])
    unit = next((u for u in ("core", "api", "web") if u not in used), None)
    if unit is None:
        continue
    num = int(story[1:])
    branch = f"cont-{story}"
    f = repo / unit / "src/main/java/com/x" / unit / f"Demo{num}.java"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("// demo continuation\n")
    def g(*a):
        subprocess.run(["git", "-C", str(repo), *a], check=True,
                       capture_output=True)
    g("checkout", "-q", "-b", branch)
    g("add", "-A")
    g("-c", "user.name=demo", "-c", "user.email=d@e.com",
      "commit", "-q", "-m", "wip")
    g("checkout", "-q", "main")
    g("merge", "--no-ff", "-q", "-m",
      f"Merge {story} into main from feature/cont (--story={num:06d})", branch)
    g("branch", "-q", "-D", branch)
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    print(story, sha, unit)
    break
EOF
)
echo "-- uscm check svc-order $SHA   (feature $STORY, new unit $UNIT)"
USCM check svc-order "$SHA"

echo
echo "== 5. watch: fold the new merge in (incremental)"
USCM watch

echo
echo "== 6. report: monthly markdown"
USCM report
echo
echo "done. workspace: $(pwd)/.uscm  |  reports: .uscm/reports/"
