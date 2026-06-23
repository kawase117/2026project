# Repo Layout

This file records the current placement rules for local work in `2026project`.

## Root

Keep the repository root limited to:

- application entry points such as `main_app.py`
- repo-wide config such as `pytest.ini`, `.gitignore`, `dbhub.toml`
- stable top-level utilities that are intentionally repo-global

Do not leave ad hoc analysis outputs or prompt drafts in root.

## Scratch

Temporary or exploratory files belong under:

- `scratch/` for ad hoc scripts, csv, txt, and one-off outputs
- `tmp/` for disposable run artifacts

These paths are git-ignored.

## Prompt And Plan Logs

Operational prompt and planning notes belong under:

- `docs/codex_prompts/` for Codex prompt drafts and execution prompts
- `docs/superpowers/plans/` and `docs/superpowers/specs/` for local planning artifacts

These paths are git-ignored so they do not pollute normal repo status.

## Analysis Code

- `eda/`: generic or cross-hall exploratory analysis
- `ml/analysis/`: hall-specific, feature-oriented deep analysis tied to ML work
- `ml/experiments/`: reproducible experiment packages and runners

If a script starts as a one-off check, keep it in `scratch/` until it is worth promoting.

## Knowledge Assets

- `document/instincts/`: tracked project knowledge and compiled instinct outputs
- `document/plans/`: tracked plans worth keeping as project history
- `document/sessions/`: tracked session summaries worth preserving

## Generated Assets

- transient generated files should be ignored when possible
- stable checked-in assets should live next to the code or docs that consume them

