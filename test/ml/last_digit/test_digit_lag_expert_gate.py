from ml.last_digit.tail_ltr_split_rule_nextday_gpu import _should_use_digit_lag_bundle


def test_digit_lag_gate_disabled_returns_false():
    assert _should_use_digit_lag_bundle(enabled=False, allowed_experts=set(), expert="3F_A") is False


def test_digit_lag_gate_enabled_with_empty_allowlist_means_all():
    assert _should_use_digit_lag_bundle(enabled=True, allowed_experts=set(), expert="2F_N") is True
    assert _should_use_digit_lag_bundle(enabled=True, allowed_experts=set(), expert="3F_A") is True


def test_digit_lag_gate_enabled_with_allowlist_filters_expert():
    allow = {"3F_N", "3F_A"}
    assert _should_use_digit_lag_bundle(enabled=True, allowed_experts=allow, expert="3F_A") is True
    assert _should_use_digit_lag_bundle(enabled=True, allowed_experts=allow, expert="2F_N") is False

