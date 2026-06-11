# Instinct Template

Use this template when recording a new instinct from EDA, verification, or code review.
Keep the core claim narrow. Separate raw observation from interpretation.

## Required Fields

```yaml
---
id: YYYY-MM-DD-short-slug
trigger: "When this instinct should be consulted"
confidence: 0.0
domain: methodology
source: session-observation
project_id: 2026project
project_name: pachinko-analyzer
---

# Short title

## Core claim
One sentence. State only the claim that is supported by the evidence.

## Evidence
- n_observations: 0
- data scope: hall / machine / segment / all-hall
- metric scope: diff / hit104 / rb_probability / transition / other
- result summary: short factual summary

## Interpretation
- What the result means operationally
- What it does not mean
- Any confounders that remain

## Action
- What to do next in EDA or operation
- If the claim is only provisional, say so explicitly

## Relation
- related:
  - another-instinct-id
- invalidates:
  - id: older-instinct-id
    reason: data_bug
    note: false signal caused by a join bug or leaked column
- supersedes:
  - id: older-instinct-id
    reason: stronger evidence at the same scope

## Status
- status: active
```

## Recommended Fields

Use these when the claim is meant to be reused by Claude/Codex in later work.

- `scope`
- `stability`
- `actionability`
- `n_observations`
- `timing_note`
- `confounders`
- `stale_reason`

## Interpretation Rules

- Keep `persistence`, `drawdown`, or similar terms as neutral transition features unless a sign and direction have already been validated.
- Do not record a feature as "effective" before the EDA result actually shows the sign and scope.
- Do not treat a general pattern as universal if the evidence is hall-specific.
- Do not upgrade a common pattern above a hall-specific pattern for operational use unless it is actually more useful in the target hall.
- If the claim depends on a minimum sample size, write the threshold in the entry.

## `invalidates` Rules

Use `invalidates` only when the older instinct is materially wrong at the same decision level.

- Use `invalidates` for:
  - data bugs
  - leakage
  - scope errors
  - confounding that changes the meaning of the claim
  - regime changes that invalidate the old operating rule
- Do not use `invalidates` for:
  - different metric scope
  - different hall
  - different granularity
  - "we found something else too"
- Do not use `invalidates` for a weaker or stronger version of the same observation unless the earlier one is actually superseded.
- If the old claim still holds in a narrower scope, mark it as `stale` or `regime_specific` instead of invalidated.

## `status` Values

- `active`: usable as-is
- `stale`: still informative, but context has changed
- `regime_specific`: valid only under a narrow historical regime
- `superseded`: replaced by a stronger or more specific instinct
- `contaminated`: invalid because the source was broken or leaked

## Example

```yaml
---
id: 2026-06-10-kamata7-new-machine-firstday-weakness
trigger: "When evaluating new-machine first-day strategy for Kamata7"
confidence: 0.91
domain: hall-strategy
source: empirical-analysis
project_id: 2026project
project_name: pachinko-analyzer
---

# New machines are weak on first days in Kamata7

## Core claim
First-day results for new machines are weaker than the post-launch baseline.

## Evidence
- n_observations: 184
- data scope: single-hall
- metric scope: diff / hit104
- result summary: first 1-3 days underperform the 30+ day bucket

## Interpretation
- Useful as a hall-specific avoidance rule
- Not a universal machine rule

## Action
- Avoid first-day entries for this hall unless other signals override

## Relation
- invalidates:
  - id: 2026-06-08-old-new-machine-hype
    reason: scope_error
    note: the old rule mixed hall-specific and cross-hall observations

## Status
- status: active
```

