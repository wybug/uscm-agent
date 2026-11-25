# Validation case: a data-warehouse script repository (out-of-sample, `dw` scheme)

An anonymized record of running the agent loop on the script repository of
a data-warehouse team, kept here as paper-supporting evidence — the paper
carries this material as §4.9 ("The same thing seen from the merges"),
§9.4 item 5 (ix), and the third replay system of §8.6. All internal
identifiers are removed; the system is described only structurally.

## System

Single repository holding a data platform's warehouse scripts
(2023-08 → 2026-11): 4,115 commits, **1,226 first-parent mainline merges**
(GitLab-style `Merge branch '…' into 'master'`; 4 direct pushes). 98% of the
changed files are SQL — MaxCompute / DataWorks tasks, DDL baselines and
per-story deployment archives — plus Python tasks named after their table.
The layout was reorganised twice (an early `scripts/` + `tables/` split,
then `init/` + `deploy/{year}/{quarter}/{date}-{id}/`), so no rule may
depend on directory positions. Part of the flow is two-level: features
sometimes land through personal branches, which is why most mainline
subjects carry no key.

## Instrument finding: the table name carries the business subject

Warehouse scripts are named after the table they build,
`{engine}_{layer}_{domain}_{subject}_…`, in the baseline, the DDL and the
deployment archive (`<id>@<data-centre>@<engine}@<db>@<layer>@<table>.sql`)
alike. The `dw` scheme therefore reads the unit off the name:
**unit = `domain.subject`** (62 units; four domains carry almost all
landings), resolved from
the script's own name first, then from `<layer>_<domain>_<subject>` or bare
layer directories. Nothing but names is read — no blob is ever fetched.

- **Attribution.** 9,939 of 12,117 script landings (82%) carry a subject.
  The rest — DDL that does not name its table, the platform's own
  databases, API templates — land in no unit: they count towards a merge's
  size but never invent a landing.
- **Layers are not units.** The ods → dwd → dws → ads direction is the
  warehouse's normative change path (the team's own review rules constrain
  calls between layers), so layers are reported (`dw.layers`) but never
  counted. The choice is normative, not empirical: 67.5% of landed merges
  touch a single layer, and with layers as units the scatter base rate
  would be 42.9% — not degenerate. With the domain alone it is 5.0%: too
  coarse to carry a signal.
- **Keys from the deploy archive.** Only 376 merges (31%) are keyed by
  their subject. 667 more carry the requirement id in the merged paths
  (the archive directory `{date}-{id}/`), keyed with `where = "path"`; 183
  have no key. 85.1% keyed → 649 merges land in ≥ 1 unit → **275
  requirements, 140 with nMR ≥ 2**.
- Bulk exceptions: 5 merges land in 13–42 subjects at once (75–2,452
  scripts: directory migrations, whole-layer synchronisations).

## Results (subject units, 140 calibration units)

| Quantity | Value | Reading |
|---|---|---|
| Local regime base rate τ | 0.393 (55/140) | replaces the prior placeholder 0.35 |
| Local refit log nMR coefficient | **+0.89** (SE 0.34; bootstrap 95% CI 0.28–1.52) | same direction and magnitude as the pooled law (+0.93) |
| Local refit GA coefficient | **−0.90** (SE 0.53; CI −1.50 to −0.35) | same direction as the pooled law (−0.61) |
| Local refit KA coefficient | +0.03 (SE 0.42) | no independent contribution, as in the pooled corpus |
| 5-fold CV AUC, local law | 0.633 [0.599, 0.651] (median and 5–95% over 200 repeats) | the tool's single split gives 0.635; do not quote one split |
| **Pooled prior, cold** | **0.668** | not below the local refit's out-of-sample value |
| log nMR alone | 0.643 | the nMR driver carries the signal |
| Direction self-check | median Φ = 1 / 2 / 2 / 5 across nMR bands | share 1.0 |
| Φ budgets (local P90) | 4 / 6 / 9.5 (bands 2–3 / 4–8 / 9+) | |
| R1′ replay precision | flagged 0.818 vs unflagged 0.314, lift 2.61 (22/118) | correlational and coupled — see below |
| Temporal stability | history cut at a calendar cut-off: n=108, log nMR +0.86, GA −0.70, τ 0.417 | same fit on the first 72% of the merges |

The law was estimated on service and middleware repositories and transfers
here cold, to a repository with no service code at all: both coefficient
directions replicate, at a magnitude close to the prior.

## What the label is made of (sensitivity)

The scatter label is "a requirement spans ≥ 3 subjects". Three name-level
counterfactuals show what that is made of (same rows, same fit):

| Variant | positives | log nMR | GA | AUC, pooled prior |
|---|---|---|---|---|
| subject units (the instrument) | 55 | +0.89 | −0.90 | 0.668 |
| bulk-landing requirements removed | 51 | +0.91 | −0.85 | 0.660 |
| units with ≤ 2 landings dropped | 52 | +1.06 | −1.08 | 0.701 |
| **serving-engine landings not counted** | 26 | +0.57 | −0.96 | 0.635 |
| layer as unit (≥ 3 layers) | 60 | +0.95 | −1.08 | 0.677 |

26.5% of attributed script landings are *serving-engine scripts* — copies,
synchronisation jobs and engine-specific versions of a table (search,
row-store, OLAP and streaming engines), recognised by engine directories
and `di_/fs_/holo_` / `2<engine>` name markers. **29 of the 55 positives
reach three subjects only through them**: the requirement's own logic
stayed inside two subjects, and its copies spread. This is the
multi-copy shape the paper names as the warehouse's real difficulty, and
the instrument sees it as scatter by design — a copy of a table lands in
the table's subject. The coefficient directions hold in every variant
(log nMR between +0.57 and +1.06, GA between −1.08 and −0.85).

## Review-tier replay

T0 12.0% · T1 75.1% · T2 1.8% · **T3 11.1%** (size ceiling 9 scripts, local
P90). Heavy-scatter rate (N1 ≥ 6 or Φ top tercile) by what drew T2/T3:
placement-triggered **0.907** (n=43), size-only 0.160 (n=25), no T2/T3
0.167 (n=72) → lift 5.43 and 0.96. Read with care: the placement trigger
is coupled to the outcome by construction, and in this repository the
tercile is 3 — "heavy" coincides with the label itself. The clean
sub-instrument (oversized merges alone) is **null here** (0.96), unlike
the 60-repository system (3.21). Every bulk landing is T3.

## Check exercise

The history was cut at a calendar cut-off (888 merges), then each of the
338 later merges was judged with the read-only `uscm check` **before**
being folded in: the check verdict equals the pre-fold replay verdict for
338/338; 10 R1′ flags under the pooled prior, 8 with a local calibration
at the cut. `uscm watch` from the same cut reproduces the full replay
merge for merge (338/338 identical tiers, same flag set). `check` never
advances the feature table — only `watch` and `init` do.

## Threats to validity

Single repository, 140 calibration units; name-level only, so a script
whose name hides its table is invisible to placement accounting. The
serving-engine split is a name heuristic reported as a counterfactual,
not used by the instrument. Feature keys depend on the deploy-archive
convention (15% of merges stay unkeyed). `mainline = true` bundles
whatever a personal branch carried. One of the 32 R1′ flags comes from a
naming accident (a table whose name fuses the domain and the subject).
All lifts are correlational.

## Reproduction shape (on your own system)

```toml
# uscm.toml
mainline = true
repos = ["/path/to/warehouse-scripts"]

[[feature]]
regex = "Merge branch '(?:[^'/]*/)?(10\\d{5})"   # your merge dialect
tag   = "S{0}"

[[feature]]                                      # keys in merged paths
regex = "/\\d{8}[-@](10\\d{5})(?:/|$)"           # deploy/<year>/<q>/<date>-<id>/
tag   = "S{0}"
where = "path"
```

```bash
uscm probe /path/to/warehouse-scripts --toml    # detects dw and the path keys
uscm init && uscm calibrate && uscm advise --top 10
uscm check warehouse-scripts <merge-sha>
```

See [THEORY.md](../THEORY.md) for the semantics ("Data-warehouse script
repositories" and "Feature keys from merged paths") and
[README.md](../README.md) for the general loop.
