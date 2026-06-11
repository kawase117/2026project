"""Compatibility wrapper for hall day strength audit utilities."""

from ml.last_digit import hall_day_strength_audit as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _name, _value, _impl
