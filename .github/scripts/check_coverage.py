"""Enforce Per-module coverage and full config-flow/diagnostics coverage."""

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
    total = summary["num_statements"] + summary["num_branches"]
    covered = summary["covered_lines"] + summary["covered_branches"]
    if total and covered * 100 <= total * 95:
        errors.append(f"{name}: {covered / total:.2%}; must exceed 95%")
    if name.endswith(("/config_flow.py", "/diagnostics.py")) and covered != total:
        errors.append(
            f"{name}: config flow/diagnostics must have 100% line and branch coverage"
        )
if not expected:
    errors.append("No integration modules found")
if errors:
    raise SystemExit("\n".join(errors))
print(
    f"Coverage passed: all {len(expected)} modules exceed 95%; config flow and diagnostics are 100%."
)
