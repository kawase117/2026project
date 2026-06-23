# Machine Master Research

This directory mixes a small number of stable inputs with many generated research artifacts.

## Keep As Stable Inputs

- `machine_list_for_research.csv`
- `machine_list_export.json`
- `machine_list_research_prompt.md`

## Generated Outputs

The following are treated as generated outputs and are git-ignored by default:

- URL map artifacts such as `machine_master_research_url_map.*`
- duplicate-resolution artifacts such as `duplicate_url_*`
- page index caches such as `1geki_slot_page_index.json`
- enhancement diffs such as `machine_master_research_diff.json`
- derived review notes such as `low_confidence_selected.md`

If any generated artifact becomes a durable project asset, promote it explicitly instead of relying on the default output location.
