"""Compatibility wrapper for hall practical strategy analysis."""

from ml.last_digit import hall_practical_strategy_analysis as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _name, _value, _impl


if __name__ == "__main__":
    raise SystemExit(main())
