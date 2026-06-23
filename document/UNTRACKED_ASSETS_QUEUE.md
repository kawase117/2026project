# Untracked Assets Queue

This file records the main untracked asset groups that remain after repo cleanup.

## Ready To Review As Project Assets

- `document/instincts/*.yaml`
  - role: project knowledge and operational findings
  - recommended action: review and accept in batches

- `eda/*.py`
  - role: generic or cross-hall exploratory scripts
  - recommended action: accept as implementation assets if still relevant

- `ml/analysis/*.py`
  - role: hall-specific deep analysis scripts
  - recommended action: accept together with matching tests where present

- `ml/experiments/*`
  - role: structured experiment packages
  - recommended action: review package boundaries, then accept as formal experiment code

- `scraper/*.py`
  - role: 1geki and machine-master support tooling
  - recommended action: accept with related tests and machine-master docs

- `test/*` and `ml/tests/*`
  - role: coverage for new EDA and experiment code
  - recommended action: accept alongside the code they verify

## Review Case By Case

- `Heatmap/static/html2canvas.min.js`
  - role: static browser asset
  - recommended action: keep only if cardmap export really depends on it

- `document/kamata7_theory.md`
  - role: standalone theory note
  - recommended action: keep if still referenced, otherwise archive under sessions or plans

- `document/plans/*.md` and `document/sessions/*.md`
  - role: durable project history
  - recommended action: keep only the items worth preserving as shared context

## Already Treated As Generated Outputs

- `ml/analysis/results/*/`
- `ml/machine_type/exploratory/output/*.json`
- `ml/machine_type/exploratory/output/*.md`
- generated `document/machine_master_research/*` artifacts listed in `.gitignore`

These are intentionally ignored unless explicitly promoted.
