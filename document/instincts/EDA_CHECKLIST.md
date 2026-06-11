# EDA Checklist

Use this checklist before, during, and after an EDA run.
The goal is to produce instincts that are reusable, not just interesting.

## 1. Before Running EDA

- State the hall scope explicitly.
- State whether the analysis is `single-hall` or `all-hall`.
- State the target metric scope.
- State the minimum sample rule.
- State whether structure is available or not.
- Check whether the candidate signal can be known at prediction time.
- Check whether any input column is same-day outcome data.
- Check whether lag or rolling features are shifted by at least one step.

## 2. Metric Selection

- Use the primary outcome first.
- If the first outcome is unstable, add a second outcome that measures the same decision question from another angle.
- Prefer a metric that changes the operational decision, not only a metric that is easy to compute.
- If the analysis is about transition behavior, do not name it as momentum until sign and direction are validated.
- Treat `tail_event_rate` style extreme-value metrics as provisional when the sample is small.
- Do not promote a metric just because it looks familiar from finance.

## 3. Leak Check

- Confirm that all signals are available before the prediction timestamp.
- Confirm that no same-day result columns are included.
- Confirm that rolling windows use prior observations only.
- Confirm that agreement features do not mix signals computed from different timestamps.
- Confirm that the feature source is not an outcome-derived aggregate.
- If there is any doubt, run an empirical check, not just a code review.

## 4. Result Review

- Record `n_observations`.
- Record the confidence level and the exact scope.
- Record the effect size, not only the p-value.
- Record the uncertainty or confidence interval when available.
- Record at least one plausible alternative explanation.
- Record whether the result is hall-specific, machine-specific, or cross-hall.
- Record whether the result is operationally useful, not only statistically interesting.

## 5. Instinct Decision

- Promote only results that are reusable in the target operation.
- If the result is still exploratory, label it as exploratory.
- If the result depends on a historical regime, mark it `regime_specific`.
- If the result is narrower than the older instinct, do not invalidate the older one unless the older one is actually wrong.
- If a bug or leak changed the meaning of the result, use `invalidates`.
- If the result is only a better phrased version of the same observation, use `supersedes`.

## 6. What To Write Into The Instinct

- `id`
- `trigger`
- `confidence`
- `domain`
- `source`
- `project_id`
- `project_name`
- `n_observations`
- `metric_scope`
- `scope`
- `stability`
- `actionability`
- `invalidates` when needed
- `status`

## 7. What Not To Do

- Do not force a universal rule when the evidence is hall-specific.
- Do not treat a noisy one-off spike as a stable pattern.
- Do not infer causality from a single strong association.
- Do not merge different timestamp assumptions into one signal agreement score.
- Do not promote a feature that cannot be computed at decision time.
- Do not overwrite a valid but stale instinct unless the old one is actually invalid.

## 8. Recommended Output Shape

- Short title
- Core claim
- Evidence
- Interpretation
- Action
- Relation
- Status

## 9. Minimum Quality Gate

Before creating or updating an instinct, answer all of these:

- What is the exact claim?
- What is the exact scope?
- How many observations support it?
- Is the feature available at decision time?
- Is this a new claim or a refinement?
- Does it invalidate an older instinct?
- Is it safe to reuse without extra context?

