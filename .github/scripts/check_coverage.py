"""Enforce 100% line and branch coverage in every integration module."""

import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
source = Path("custom_components/ha_flightseats")
expected = {path.as_posix() for path in source.glob("*.py")}
files = report["files"]
errors = []
for name in sorted(expected):
    if name not in files:
        errors.append(f"{name}: missing from coverage report")
        continue
    summary = files[name]["summary"]
    if "num_branches" not in summary:
        errors.append(f"{name}: branch coverage was not collected")
        continue
    missing_lines = summary["num_statements"] - summary["covered_lines"]
    missing_branches = summary["num_branches"] - summary["covered_branches"]
    if missing_lines or missing_branches:
        errors.append(
            f"{name}: {missing_lines} uncovered lines and "
            f"{missing_branches} uncovered branches; both must be zero"
        )
if not expected:
    errors.append("No integration modules found")
if errors:
    raise SystemExit("\n".join(errors))
print(
    f"Coverage passed: all {len(expected)} modules have 100% line and branch coverage."
)
