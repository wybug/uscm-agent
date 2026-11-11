# Validation case: a DDD-layered monorepo (out-of-sample)

An anonymized record of running the full agent loop on a real engineering
repository, kept here as paper-supporting evidence. All internal identifiers
are removed; the system is described only structurally.

## System

Single git repository of an internal business system (2023-11 → 2026-11):
2,407 commits, **402 first-parent mainline merges** (one direct push, i.e. no
squash-merge workflow). Seven Maven modules arranged as **DDD architecture
layers** (adapter / application / client / common / domain / entry /
infrastructure). Merge subjects follow `Merge branch 'feature/<7-digit-id>'
into 'master'`; **383/402 merges (95.3%) carry a feature key** → 142 story
features. The 19 unkeyed merges (hotfix/revert branches) update statistics
but receive no feature-level verdicts, by design.

## Instrument finding: module-level label degeneracy

With default module units, **94% of features with nMR ≥ 2 span ≥ 3 modules**
(79/84) — the module-level scatter label carries no information. The cause
is architectural: modules are *layers*, and crossing adapter → application →
domain → infrastructure is the normative structure of every full-stack
feature, exactly parallel to the front-end case (page → api → component
crossings are normative; scatter = crossing *pages*).

`uscm calibrate` detects this automatically (label-degeneracy warning at
base rate ≥ 0.90) and the workspace re-operationalizes with
`unit_style = "pkg"`: units become **business package segments** — the
package path stripped of the repo-wide prefix and the module-name segment,
stepping over technical stereotype packages (dto / service / mapper / http /
gateway / …). A change that never reaches a business segment lands in no
unit. Scatter then means *spanning ≥ 3 business capabilities* — the third
documented operationalization of the same principle (module → page →
business package).

## Results (pkg units, 138 features, 75 with nMR ≥ 2)

| Quantity | Value | Reading |
|---|---|---|
| Local regime base rate τ | 0.773 | locally calibrated, replaces prior placeholder 0.35 |
| Local refit log nMR coefficient | **+0.69** (SE 0.53) | same direction as pooled law (+0.93) — the main driver replicates |
| Local refit GA coefficient | +0.23 (SE 0.67) | not significant at n = 75; magnitude does not transfer, as the paper states |
| 5-fold CV AUC (local law) | 0.577 | weak but above chance on a single repo |
| Direction self-check | Φ monotone non-decreasing in nMR, share = 1.0 | passes |
| Regime share drift | prior-6m 1.00 → recent-6m 0.588 | scatter regime contracting in recent history |
| **R1′ replay alarm precision** | flagged 0.692 vs unflagged 0.371, **lift 1.87** (13 flagged / 62 unflagged) | **replicates the pooled-corpus replay lift of 1.88** on an out-of-sample system with a different unit operationalization |

The replay ran over all 402 merges with pre-event information only and
frozen pooled coefficients (τ = 0.35 prior placeholder), producing 16
historical flags. Spot checks confirm the extraction: the most scattered
feature spans 16 business packages across 9 merges
(customer×6, advance×4, credit×3, bill×3, statement×3, …); the largest Φ
is 19, which trips the Φ-budget alarm in its nMR band.

## Review-tier replay (v0.2, two further systems)

v0.2 adds review tiers (T0 auto+sample / T1 standard / T2 deep+placement /
T3 split-first; see THEORY.md). Replaying whole histories draws a tier for
every merge *before* it is folded (pre-event information only; file-count
thresholds come from merges already replayed, and the local P90 may only
tighten — never loosen — the configured size ceiling). Three semantic rules
were forced by this replay and are now asserted in tests: (a) the shape
gate precedes the feature gates — a feature's first bulk drop and an
unkeyed oversized merge are T3 material; (b) *attribution asymmetry* — a
multi-unit merge routes to T3-decompose only when keyed (a footprint
expansion: new units, or the feature's first drop); unkeyed multi-unit
merges (release-line rollup remnants) and syncs of existing landings are
atomic or unattributable, so they get per-unit review focus at T1/T2
instead (mirroring R1′, which also demands a key before placement claims);
(c) ladder coherence — the size ceiling stays strictly above the T0 file
ceiling even on degenerate distributions, which is surfaced as
`degenerate` rather than silently patched.

**System A — 3 repositories, 523 merges, 168 story features** (backend +
front-end, business-package and page units; locally calibrated: τ=0.548,
CV AUC 0.699). Distribution: T0 4.2% · T1 79.7% · T2 0.2% · **T3 15.9%**
(60 oversized-only · 13 both · 10 multi-unit-expansion). Features that drew
≥1 T2/T3 merge ended heavily scattered (N1 ≥ 6 or within-repo Φ top
tercile, nMR ≥ 2) **0.737 vs 0.391** → lift **1.885** (19 vs 23 features)
— in line with the R1′ lineage (1.87/1.88). Sanity anchor: the feature
behind the original Φ-budget ALARM (Φ=4 in band P90=4) is routed to T2 for
*any* follow-up merge — via the Φ budget when staying in existing units,
via P(next)=0.60 > τ when adding a unit.

**System B — 60 repositories pooled, 15,063 merges** (multi-tier flows,
staging grafts, prior calibration per repository). Distribution: T0 4.0% ·
T1 76.3% · T2 0.05% · **T3 19.7%**. ≥1 T2/T3 features: 331, heavy-scatter
rate **0.662**; rest: 256, **0.156** → pooled lift **4.23**. Reading
caution: the multi-unit-expansion trigger is construct-coupled to the
outcome (a merge adding units is on the causal path to high final N1), so
the pooled lift over-states independent evidence. The cleaner
sub-instrument — features that ever drew an *oversized* T3 (size ceiling
alone, independent of unit counts) — separates at **0.882 vs 0.275**,
lift **3.21** (161 vs 426 features). Under cold-start calibration T2 fires
almost only on R1′ FLAGs (local Φ bands do not exist yet); the size and
shape gates carry the replay.

Readings: (i) tiers are *conservative* under cold start; (ii) T0's 4% share
is the placement-dimension attention budget released to machine checks +
sampling — small in these systems because most merges touch several files
(> local P50); it is not a correctness verdict; (iii) a T3 share of 16–20%
is this ecosystem's honest reading (41% of stories span ≥3 repositories;
bundled placement expansion and oversized merges are common), not an
instrument artifact — the attribution and sync exclusions removed the
tautological cases (23 sync + 1,545 unattributed multi-unit merges) with
no change in feature-level lift; (iv) all lifts are correlational with
within-repository labels, same caveats as the R1′ lift.

## Threats to validity

Single system, single repository, 75 calibration units; coefficients beyond
the nMR driver are not identified at this n. The lift is correlational (the
model flags scatter *risk*, not the causal effect of placement). Feature
keys depend on branch-name discipline (95% coverage here); systems with
sloppier dialects lose feature-level coverage, not merge-level accounting.

## Reproduction shape (on your own system)

```toml
# uscm.toml
mainline   = true
unit_style = "pkg"          # for DDD-layered monorepos
repos      = ["/path/to/your-repo"]

[[feature]]
regex = "branch '(?:feature/)?(\\d{5,})"   # your merge dialect
tag   = "S{0}"
```

```bash
uscm init && uscm calibrate && uscm advise --top 10 && uscm report
```

See [THEORY.md](../THEORY.md#ddd-layered-monorepos-unit_style--pkg) for the
semantics and [README.md](../README.md) for the general loop.
