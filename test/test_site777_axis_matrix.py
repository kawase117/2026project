import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper", "site777"))

import site777_axis_matrix as am  # noqa: E402


def _machine(number, name, games, rb, bb, diff=None):
    return {
        "machine_number": str(number),
        "model_name": name,
        "games": games,
        "rb_count": rb,
        "bb_count": bb,
        "latest_diff": diff,
    }


def _fixture():
    machines = []
    layout_full = {}
    for i in range(6):
        number = 100 + i
        machines.append(_machine(number, "N", 3000, 10 + i, 12))
        layout_full[number] = ("100-105", i + 1, 6 - i, 0)
    for i in range(6):
        number = 200 + i
        machines.append(_machine(number, "A", 3000, 5, 0, diff=-500 + 400 * i))
        layout_full[number] = ("200-205", i + 1, 6 - i, 0)
    by_norm = {"N": ("N", "ノーマル"), "A": ("A", "AT")}
    return machines, layout_full, by_norm


def test_all_required_pairs_are_produced():
    machines, layout_full, by_norm = _fixture()
    _out, produced = am.build(machines, {}, layout_full, by_norm, lambda s: s, 3000.0)
    assert am.missing(produced) == []


def test_missing_reports_dropped_pair():
    machines, layout_full, by_norm = _fixture()
    _out, produced = am.build(machines, {}, layout_full, by_norm, lambda s: s, 3000.0)
    produced.discard(("AT", "末尾"))
    assert am.missing(produced) == [("AT", "末尾")]


def test_bb_and_games_are_reported_for_judgeable_tail_table():
    machines, layout_full, by_norm = _fixture()
    out, _produced = am.build(machines, {}, layout_full, by_norm, lambda s: s, 3000.0)
    text = "\n".join(out)
    tail_block = text.split(am.heading("判別可能", "末尾"))[1].split("###")[0]
    assert "総G" in tail_block and "平均G" in tail_block and "BB比" in tail_block
