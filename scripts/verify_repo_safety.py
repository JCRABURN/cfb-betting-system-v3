"""Fail closed when dependency or GitHub workflow safeguards regress."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_REPOSITORY = "JCRABURN/cfb-betting-system"
PRODUCTION_WORKFLOWS = (
    "midweek_line_pull.yml",
    "post_game_audit.yml",
    "weekly_report.yml",
)
PINNED_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*==[^;\s]+(?:\s*;\s*.+)?$"
)


def requirement_errors(text: str, source: str) -> list[str]:
    """Return errors for dependency lines that are not exact pins."""
    errors: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            if source != "requirements-dev.txt" or line != "-r requirements.txt":
                errors.append(f"{source}:{line_number}: requirement include is not allowed: {line}")
            continue
        if not PINNED_REQUIREMENT.fullmatch(line):
            errors.append(f"{source}:{line_number}: dependency is not exactly pinned: {line}")
    return errors


def production_workflow_errors(text: str, source: str) -> list[str]:
    """Return errors for a copied data-writing workflow that could run in V3."""
    errors: list[str] = []
    if re.search(r"(?m)^\s{2}schedule:\s*(?:#.*)?$", text):
        errors.append(f"{source}: production schedule trigger is forbidden in V3")
    if not re.search(r"(?m)^\s{2}workflow_dispatch:\s*(?:#.*)?$", text):
        errors.append(f"{source}: controlled manual dispatch trigger is missing")

    guard_pattern = re.compile(
        rf"(?m)^\s{{4}}if:\s*github\.repository == '{re.escape(PRODUCTION_REPOSITORY)}'\s*$"
    )
    if not guard_pattern.search(text):
        errors.append(f"{source}: exact production-repository allow-list guard is missing")

    if not re.search(r"(?m)^permissions:\s*\r?\n\s{2}contents:\s*read\s*$", text):
        errors.append(f"{source}: workflow-level permissions must default to read-only")
    if not re.search(r"(?m)^concurrency:\s*$", text):
        errors.append(f"{source}: top-level concurrency control is missing")
    if not re.search(r"(?m)^\s{2}cancel-in-progress:\s*false\s*$", text):
        errors.append(f"{source}: data-writing runs must serialize without cancellation")
    if "python -m pip install --requirement requirements.txt" not in text:
        errors.append(f"{source}: workflow does not install the runtime dependency lock")
    return errors


def ci_workflow_errors(text: str, source: str = "ci.yml") -> list[str]:
    """Return errors when pull-request CI gains unsafe privileges or triggers."""
    errors: list[str] = []
    if not re.search(r"(?m)^\s{2}pull_request:\s*$", text):
        errors.append(f"{source}: pull_request trigger is missing")
    if re.search(r"(?m)^\s{2}(schedule|workflow_dispatch):\s*", text):
        errors.append(f"{source}: CI must remain pull-request-only")
    if re.search(r"(?m)^\s{2}pull_request_target:\s*", text):
        errors.append(f"{source}: pull_request_target is forbidden")
    if not re.search(r"(?m)^permissions:\s*\r?\n\s{2}contents:\s*read\s*$", text):
        errors.append(f"{source}: CI must use read-only repository permissions")
    if re.search(r"(?m)^\s+contents:\s*write\s*$", text):
        errors.append(f"{source}: CI must not grant write permissions at any scope")
    if "${{ secrets." in text:
        errors.append(f"{source}: CI must not receive repository secrets")
    if "cancel-in-progress: true" not in text:
        errors.append(f"{source}: superseded CI runs must be cancelled")
    if "python -m pip install --requirement requirements-dev.txt" not in text:
        errors.append(f"{source}: CI does not install the development dependency lock")
    if "python scripts/verify_repo_safety.py" not in text:
        errors.append(f"{source}: CI does not enforce repository safety checks")
    if "python -m scripts.verify_migrations" not in text:
        errors.append(f"{source}: CI does not verify migrations on a disposable copy")
    if "python -m pytest -q" not in text:
        errors.append(f"{source}: CI does not run the complete test suite")
    return errors


def repository_errors(root: Path = ROOT) -> list[str]:
    """Validate the checked-in dependency locks and workflow configuration."""
    errors: list[str] = []

    requirements = root / "requirements.txt"
    dev_requirements = root / "requirements-dev.txt"
    errors.extend(requirement_errors(requirements.read_text(encoding="utf-8"), requirements.name))
    dev_text = dev_requirements.read_text(encoding="utf-8")
    errors.extend(requirement_errors(dev_text, dev_requirements.name))
    if dev_text.splitlines().count("-r requirements.txt") != 1:
        errors.append("requirements-dev.txt: runtime dependency lock must be included exactly once")

    workflow_dir = root / ".github" / "workflows"
    for filename in PRODUCTION_WORKFLOWS:
        path = workflow_dir / filename
        errors.extend(production_workflow_errors(path.read_text(encoding="utf-8"), filename))

    ci_path = workflow_dir / "ci.yml"
    errors.extend(ci_workflow_errors(ci_path.read_text(encoding="utf-8"), ci_path.name))
    return errors


def main() -> int:
    errors = repository_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Repository dependency and workflow safety checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
