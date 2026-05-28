from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _should_use_2fn_weekday_patch


def test_2fn_patch_disabled():
    assert _should_use_2fn_weekday_patch(enabled=False, expert="2F_N") is False


def test_2fn_patch_enabled_only_for_2fn():
    assert _should_use_2fn_weekday_patch(enabled=True, expert="2F_N") is True
    assert _should_use_2fn_weekday_patch(enabled=True, expert="3F_N") is False
    assert _should_use_2fn_weekday_patch(enabled=True, expert="3F_A") is False

