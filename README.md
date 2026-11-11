# uscm-agent

**A placement-decision agent for microservice / multi-module business systems** — it
keeps technical debt and complexity within reason across continuous iteration by
governing *where changes land*, which is where structural debt compounds.

This is the software artifact of the USCM-CC change-cost model (paper: *"USCM-CC:
a unified currency for change cost"*; see [THEORY.md](THEORY.md) for the
code↔theory map). The statistical core is deterministic, auditable, and
reproducible; it is exposed twice — as a CLI for humans and CI, and as an MCP
server for AI coding agents.

![CI](https://github.com/wybug/uscm-agent/actions/workflows/ci.yml/badge.svg)

## The idea in six lines

1. Features (stories) are touched again and again. If every touch lands in the
   same module, cost per change stays flat — that is what "placed correctly"
   means operationally.
2. When a feature's landings spread across many modules ("scatter"), later
   changes must touch several of them; scatter is a *compounding debt*, not a
   static smell.
3. Scatter is a **regime**, and the regime is **predictable from git history
   alone**: `logit P(scatter) = -1.01 + 0.93·log(nMR) − 0.01·KA − 0.61·GA`
   (nMR = merges on the feature, KA/GA = author count / author concentration).
4. The pooled law **transfers cold**: on a held-out 74-repository microservice
   system, frozen coefficients scored AUC 0.586 vs 0.592 for a local refit
   (Java business repos 0.60–0.85; front-end ~0.51 — recalibrate locally).
5. So the guardrail can run from day one on prior coefficients and sharpen
   monthly with local telemetry — a *two-layer calibration*.
6. A historical replay (26 repos, 1,125 features, pre-event information only)
   showed flagged features ended up heavily scattered 0.81 vs 0.43 unflagged
   (**lift 1.88**) — the first decision-validity result; correlational.

## What it decides

| Rule | Decision | Command |
|---|---|---|
| **R1′ anti-scatter guardrail** | A merge that introduces a *new* placement unit to a feature whose P(scatter) exceeds the system base rate τ is flagged: demand a placement rationale or re-place. | `uscm check REPO SHA` (single merge, CI) · `uscm watch` (incremental daily) |
| **R2′ narrow first** | For features above τ: rank their existing units — keep changes inside them; do not widen Ω when scatter risk is high. | `uscm advise --story KEY` |
| **Φ budget** | A feature's landing count Φ crossing its nMR-band's local P90 is a split/relocate candidate. No cross-system Φ bound exists — budgets are strictly local. | `uscm advise` |
| **R3′ local anomaly** | A feature whose last ≥3 merges each run materially above its own size baseline gets marked for human review (a statistical marker, not proof of debt). | `uscm advise` |
| **Review tiers T0–T3** | Every merge draws a review tier from the same pre-event signals: **T3** split-first (oversized — local P90 tightens, never loosens, the configured ceiling — or a keyed merge expanding the footprint across ≥3 units) · **T2** deep + placement discussion (R1′ FLAG or prospective Φ over budget; placement rationale required) · **T1** standard (multi-unit syncs and unattributed merges get per-unit review focus) · **T0** auto + sampling (placement dimension only, never certifies correctness). | `uscm check` (review block) · `uscm reviewstats` |
| **Two-layer calibration** | Monthly local refit of the law, τ = local regime base rate, Φ bands recomputed, plus three self-checks (direction / regime drift / alarm precision). | `uscm calibrate` |

Verdict ladder for a merge: `FLAG` / `PASS` / `OK` (skip: no feature key · no
source units · feature's first merge). Every evaluation uses **pre-event
information only** — the replay loop judges each merge strictly before folding
it into the feature table.

## Quickstart (10 minutes, zero data needed)

```bash
git clone <this-repo> && cd uscm-agent
python3 -m venv .venv && .venv/bin/pip install -e ".[test,mcp]"
bash demo/demo.sh
```

The demo generates a deterministic synthetic microservice system (8 repos, 60
features; scatter planted from the regime law itself), then runs the whole
loop. Trimmed output:

```
== 1. init: scan repos, replay history with the frozen pooled prior
  svc-order      scheme=multi   merges=53
  portal-web     scheme=front   merges=12
  ...
  features: 60   merges replayed: 263   historical R1' flags: 24

== 2. calibrate: local refit + tau + Phi budgets + self-checks
mode: local   units: 60   tau: 0.283 (local-base-rate)
coef: intercept=-1.5  log_nMR=1.5  KA=-0.36  GA=-1.41     # planted: +0.9 / -0.6
local fit 5-fold CV AUC: 0.819

== 4. check: single-merge verdict + review tier (read-only)
FLAG: new-unit-above-tau  S000016  svc-order#4f679cb9
  P(scatter)=0.701  tau=0.283  nMR_prev=12  GA=0.21  new_units=['core']
  [R1' anti-scatter guardrail] This merge introduces new placement unit(s)
  [core] for feature S000016, whose P(scatter)=70% exceeds the system base
  rate tau=28% ... State the placement rationale, or place into an existing
  unit / narrow the options first (R2').
  review: T2  triggers: new-unit-above-tau  units_in_mr=1  files=1
  [review T2 | deep + placement] R1': P(scatter)=70% exceeds tau=28%. Attach
  a placement rationale (candidate units, why this one, sync plan with
  existing landings); senior review owns the alignment layer.
```

The calibration recovering the planted directions (`log_nMR > 0`, `GA < 0`)
is asserted in CI (`tests/test_e2e_synth.py`).

## Using it on your system

```bash
mkdir ws && cd ws
cat > uscm.toml <<'EOF'
since = "2024-01-01"
repos = ["~/code/my-system/*"]        # paths or globs; any mix of git repos

[[feature]]                           # optional: your story-id dialect
regex = "PROJ-(\\d+)"
tag   = "PROJ-{0}"
EOF

uscm init                # replay history with frozen prior (cold start)
uscm calibrate           # local law, tau, Phi bands, self-checks
```

Before writing `uscm.toml` by hand, run the read-only workflow pre-analysis
on each repo — it derives the config from evidence instead of guesswork:

```bash
uscm probe ~/code/my-repo          # branch workflow, story dialect, unit style
uscm probe ~/code/my-repo --toml   # emits a uscm.toml scaffold
uscm probe ~/code/my-repo --json   # machine output incl. the staging graft list
```

`probe` classifies every merge (landing / line-rollup / review-iteration /
sync / feature-internal), discovers the landing lines (direct vs
release-train flows, fast-forward eras), proposes the story-key regex from
source-branch digit shapes, warns on squash workflows (near-zero keyed
coverage) and multi-line inheritance (per-line worktrees double-count), and
pre-checks unit-style degeneracy (`module` units that are just architecture
layers → `pkg`; class-prefix services → `camel`). For two-level flows it
recommends staging: clone `--shared`, graft out the listed nested merges
(`git replace --graft`), run with `mainline = false`.

Then operate:

- **daily / hourly**: `uscm watch [--fetch]` — judges new merges, appends flags;
- **in CI on every MR**: `uscm check REPO SHA --json` — parse `verdict`
  (`FLAG` → block or request rationale) and `review.tier`
  (T3 → ask for decomposition along placement units; T2 → request the
  placement rationale; comment text is ready to post);
- **monthly**: `uscm calibrate && uscm report` — refit, self-check, archive a
  markdown report under `.uscm/reports/`; then `uscm reviewstats` — tier
  distribution, T0 share (attention saved), T2/T3 outcome lift;
- **anytime**: `uscm advise --top 10` — the current scatter-risk leaderboard.

Module schemes are auto-detected per repo: Maven multi-module (`multi`),
single-tree Java packages (`single`), directory-prefix modules for Go/TS
(`flat2`), and front-end repos (`front`), where **only distinct pages count as
placement units** — page→api→component layer crossings are normative
structure, and scatter means *crossing pages*. Front-end repos under the
pooled prior emit a warning: recalibrate locally first.

### MCP integration (for AI coding agents)

```bash
pip install 'uscm-agent[mcp]'
```

Register in any MCP client (e.g. Claude Code `mcpServers`, cursor, etc.):

```json
{
  "mcpServers": {
    "uscm": {
      "command": "uscm",
      "args": ["mcp"],
      "env": {},
      "cwd": "/absolute/path/to/ws"
    }
  }
}
```

Tools: `uscm_status`, `uscm_calibration`, `uscm_check(repo, sha)`,
`uscm_advise(story?, top?)` — all return the same deterministic JSON the CLI
produces. An agent working on a change calls `uscm_check` before proposing a
PR, and `uscm_advise` to learn which existing units a risky feature should
stay inside (R2′).

## Evidence and limits

| Result | Value | Source |
|---|---|---|
| Pooled regime law | β(log nMR)=0.93±0.07, β(GA)=−0.61±0.16; n=3,010 units / 19 repos | 5-fold CV AUC 0.623 |
| Cold transfer (pooled) | leave-one-repo-out AUC 0.634 | same corpus |
| Out-of-sample system | 74 repos / 2,882 units: frozen-coef AUC 0.586 ≈ local refit 0.592; Java 0.60–0.85, front-end ~0.51 | held-out microservice system |
| R1′ replay (decision validity) | τ=0.38, 164 flags / 10 months; flagged → heavily scattered (N₁≥6) 0.81 vs 0.43 (**lift 1.88**); Φ top-tercile lift 1.64 | per-merge replay, pre-event info only — *correlational* |
| Out-of-sample DDD-layered monorepo | 402 mainline merges / 138 features; module-level label degenerate (94%) → business-package units; local law log nMR **+0.69** (direction replicates); replay precision 0.692 vs 0.371 (**lift 1.87**) | [validation case](docs/validation-case.md) |
| Φ universal scale law | rejected (R² median 0.09) → replaced by local quantile budgets | model v2 |

**Boundary declaration** (ships with every deployment): this model provides
directions, rankings, probabilities and budget alarms only. No absolute cost
prediction. No feature-level defect prediction (tested null across three
instruments). All thresholds require monthly local recalibration; magnitudes
do not transfer across systems, directions and rankings do.

## Repository map

```
src/uscm/model.py       regime law, logistic fit (IRLS), AUC, Phi bands
src/uscm/modules.py     module-scheme detection & placement units
src/uscm/features.py    git merge history -> feature units
src/uscm/guard.py       R1': replay / watch / check
src/uscm/calibrate.py   two-layer calibration + three self-checks
src/uscm/advise.py      R2' narrowing, Phi budget, R3' anomaly
src/uscm/review.py      review tiers T0-T3 + replay-log stats
src/uscm/report.py      monthly markdown report
src/uscm/synth.py       deterministic synthetic-system generator (demo/tests/CI)
src/uscm/mcp.py         MCP server for coding agents
docs/validation-case.md    anonymized out-of-sample validation record
priors/regime_pooled.json   frozen pooled coefficients + provenance
```

See [THEORY.md](THEORY.md) for the precise mapping between commands and the
paper's constructs, and [README.zh-CN.md](README.zh-CN.md) for the Chinese
edition.

## Citation

See [CITATION.cff](CITATION.cff). Please cite both the artifact and the paper.

## License

MIT.
