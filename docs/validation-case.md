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
