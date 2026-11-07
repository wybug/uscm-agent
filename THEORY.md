# THEORY.md — code ↔ paper map

This artifact implements the **decision view** of the USCM-CC change-cost
model (paper draft: §3.10 decision view; §9.4 item five (vi)–(vii) evidence;
§1.4 two-layer calibration; model-v2 §2–3). Every quantity that enters the
model declares its instrument first ("no instrument, no model"); the table
below maps each construct to the code that measures and uses it.

## Constructs

| Paper construct | Instrument | Code |
|---|---|---|
| Feature F (story) | merge-commit subjects via configurable regex list | `features.py::feature_key` |
| nMR(F) — merges on the feature | git merge history (first-parent diffs) | `features.py::list_merges/merge_files` |
| KA / GA — author count / concentration | branch-commit authors; GA = 1 − H(p)/log KA | `model.py::ga_of` |
| N₁ — placement units spanned | module schemes: `multi` (Maven dirs), `single` (package L1), `flat2` (first two dirs), `front` (distinct pages) | `modules.py` |
| Φ — landing count | distinct placement units of F | `state.py::update_feature` |
| Scatter regime | N₁ ≥ 3 modules; front-end: ≥ 2 distinct pages | `calibrate.py::feature_is_scattered` |
| Placement-regime law (replaces Eq. 51) | logit P(scatter) = b₀ + b₁·log nMR + b₂·KA + b₃·GA | `model.py::p_scatter`, `priors/regime_pooled.json` |
| Local law refit | ridge logistic IRLS + rank AUC | `model.py::fit_logit/auc` |
| Φ quantile budget (replaces Φ_max) | per-nMR-band P90, rolling local data | `model.py::phi_band_table` |

## Decision rules (§3.10)

**R1′ anti-scatter guardrail** (`guard.py::evaluate_merge`). A merge is
`FLAG` iff all of: (a) it carries a feature key; (b) it lands in ≥1 source
placement unit; (c) the feature has ≥1 prior merge; (d) the merge introduces
≥1 unit new to the feature; (e) P(scatter), computed from the feature table
*as it stood before this merge*, exceeds τ. Otherwise `PASS` (evaluated,
below threshold) or `OK` (skip, with reason). τ defaults to the local regime
base rate after calibration; before that it is a configurable placeholder
(0.35) and every output says which is in force (`tau_source`).

**R2′ narrow first** (`advise.py`). For features above τ the report ranks
their existing units by landing count: the narrowing move is to keep changes
inside units the feature already occupies. This narrows the *inputs the
probability model can see* (placement clarity, authorship), not any single
cohesion metric — Γ is a heuristic construct in the paper, deliberately not
an upstream variable here.

**Φ budget** (`model.py::phi_band_table`, `advise.py`). Alarm when Φ crosses
the local P90 of the feature's nMR band (bands 1 / 2–3 / 4–8 / 9+; a band
needs ≥10 units or the alarm stays off). Φ has no universal scale law
(rejected empirically, R² median 0.09), so no cross-system bound is offered.

**R3′ local anomaly** (`advise.py::r3_anomaly`). A feature's last ≥3 merges
each ≥ max(1.5× median, median+2) files of its own earlier baseline → marked
for human review. A statistical alarm; the paper explicitly does *not* read
it as proof of debt (feature-level quality decay tested null).

**Front-end operationalization.** In `front` schemes only `page:` units
count; page→api→component crossings are normative layered structure.
Feature-level scatter label = ≥2 distinct pages. Because the pooled prior was
not estimated with this label, front-end repos under prior calibration carry
a warning and require local recalibration before thresholds are trusted.

## Two-layer calibration (§1.4) and self-checks

`calibrate.py`. Layer 1 — the pooled prior
(`priors/regime_pooled.json`: intercept −1.01, log nMR 0.93±0.07, KA −0.01,
GA −0.61±0.16; n=3,010 units / 19 repos; CV AUC 0.623; leave-one-repo-out
0.634; out-of-sample 74-repo system 0.586 ≈ local refit 0.592). Layer 2 —
monthly local refit (needs ≥40 units and ≥8 per class; otherwise the prior
stays with an explicit note), τ = local base rate, Φ bands recomputed, and
three self-checks:

1. **direction** — share of repos whose median Φ is non-decreasing across
   nMR bands;
2. **regime drift** — scatter share, last 6 months vs prior 6 months;
3. **alarm precision** — share of flagged features that ended heavily
   scattered (N₁≥6 or Φ top-tercile) vs unflagged, with lift.

## Replay semantics (no lookahead)

`init` replays all merges in **global date order across repos**, judging each
merge before folding it into the feature table — so cross-repo features get
exactly the pre-event information the paper's guardrail replay used. `watch`
processes new merges per repository (batch order within a repo by date), the
same approximation as the validated dry-run; `check` evaluates read-only
against the current table (intended for merges not yet folded in).

## Known semantics decisions

- **Unit names are repo-local strings, unprefixed.** A feature table merges
  `core` of two different repos into one unit — identical to the research
  pipeline that produced and replay-validated the rule. Cross-repo scatter is
  therefore counted by module *name*, which is how shared-hub scatter
  (`platform-common`-style commons) shows up.
- **Sources counted**: Java under `src/main/java`, Go (no `vendor/`, no
  `_test.go`), TS/TSX/Vue/JSX (no `node_modules/`, `dist/`, `.d.ts`,
  `.test./.spec.`). `.vue/.jsx` support is an extension beyond the original
  pipeline (which was Java/Go/TS only).
- **Feature-key dialects** are config (`uscm.toml` `[[feature]]`), defaults:
  `--story=N` / `story/N`, JIRA-like `[A-Z]+-\d+`, `TAPD N`. Merges without
  a key update statistics but produce no feature-level verdicts.
- **Mainline merges only** (default; config `mainline`). The unit of change
  is a first-parent merge onto the mainline — one merged request. Nested
  merges inside feature branches and direct pushes are invisible by design.
  Squash-merge workflows (no merge commits) are not covered by this
  instrument; detect them by a near-empty `--merges` log before deploying.

## Anonymization

The shipped prior contains aggregate statistics only (coefficients, counts,
AUCs) as published in the paper. No repository names, hosts, or author
identities from any calibration corpus appear in this repository; the demo
and CI corpus is fully synthetic and deterministic (`synth.py`, seeded).

## Boundary declaration

Directions, rankings, probabilities and budget alarms only. No absolute cost
prediction; no feature-level defect prediction (tested null); thresholds
require monthly local recalibration; magnitudes do not transfer across
systems, directions and rankings do.
