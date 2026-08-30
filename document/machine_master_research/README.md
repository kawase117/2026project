# Machine Master Research

This directory mixes a small number of stable inputs with many generated research artifacts.

## Keep As Stable Inputs

- `machine_master.csv` (canonical machine master, including `source_url` and resolution provenance)
- `machine_list_research_prompt.md`

Raw hall labels are retained in `machine_name`; `canonical_machine_name` is the join/grouping key.
Manufacturer and type dimensions are separately normalized into `manufacturer_canonical`,
`cabinet_type`, `game_type`, and `bt_flag`.

Setting-level values that are not BB/RB have dedicated columns: `at_initial_setting*`,
`bonus_initial_setting*`, `bonus_combined_setting*`, `combined_initial_setting*`, and
`rtp_complete_setting*`. Source freshness is recorded in `source_title` and
`source_checked_at`. Do not parse identity, source URLs, or setting values back out of `notes`.

## Generated Outputs

The following are treated as generated outputs and are git-ignored by default:

- one-off URL-resolution audits such as `url_resolution_audit*.json` (only when candidate details are needed)
- duplicate-resolution artifacts such as `duplicate_url_*`
- page index caches such as `1geki_slot_page_index.json`
- enhancement diffs such as `machine_master_research_diff.json`
- derived review notes such as `low_confidence_selected.md`

If any generated artifact becomes a durable project asset, promote it explicitly instead of relying on the default output location.
