"""Compatibility wrapper for the hall GPU/LTR model zoo."""

from ml.last_digit import hall_gpu_model_zoo as _impl

for _name, _value in vars(_impl).items():
    if _name.startswith("__"):
        continue
    globals()[_name] = _value

del _name, _value, _impl


if __name__ == "__main__":
    raise SystemExit(main())
