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
V3_PRODUCTION_WORKFLOW = "v3_production_operations.yml"
V3_PRODUCTION_OPERATIONS = (
    "tuesday_lock",
    "wednesday_refresh",
    "thursday_refresh",
    "friday_refresh",
    "saturday_final",
    "postgame_grading",
    "weekly_audit",
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


def v3_production_workflow_errors(
    text: str,
    source: str = V3_PRODUCTION_WORKFLOW,
) -> list[str]:
    """Return errors when the manual V3 cutover gateway stops failing closed."""
    errors: list[str] = []
    if re.search(r"(?m)^\s{2}schedule:\s*(?:#.*)?$", text):
        errors.append(f"{source}: production schedule trigger is forbidden before approval")
    if not re.search(r"(?m)^\s{2}workflow_dispatch:\s*(?:#.*)?$", text):
        errors.append(f"{source}: controlled manual dispatch trigger is missing")
    if re.search(r"(?m)^\s{2}pull_request_target:\s*", text):
        errors.append(f"{source}: pull_request_target is forbidden")
    if "github.repository == 'JCRABURN/cfb-betting-system-v3'" not in text:
        errors.append(f"{source}: exact V3 repository allow-list guard is missing")
    for required_guard in (
        "vars.CFB_V3_PRODUCTION_ENABLED == 'true'",
        "vars.CFB_V3_OPERATION_EXECUTION_ENABLED == 'true'",
        "vars.CFB_V3_KILL_SWITCH == 'false'",
        "vars.CFB_V3_OWNER_CUTOVER_APPROVED == 'true'",
        "inputs.confirmation == 'RUN_V3_OPERATION'",
    ):
        if required_guard not in text:
            errors.append(f"{source}: required fail-closed guard is missing: {required_guard}")
    if "environment: v3-production" not in text:
        errors.append(f"{source}: protected v3-production environment is missing")
    if "runs-on: [self-hosted, cfb-v3-production]" not in text:
        errors.append(
            f"{source}: authoritative SQLite execution requires the dedicated durable runner"
        )
    if not re.search(r"(?m)^permissions:\s*\r?\n\s{2}contents:\s*read\s*$", text):
        errors.append(f"{source}: workflow-level permissions must default to read-only")
    if re.search(r"(?m)^\s+contents:\s*write\s*$", text):
        errors.append(f"{source}: cutover-readiness workflow must not grant write permissions")
    writer_group = (
        "group: v3-production-writer-${{ github.repository }}-"
        "${{ inputs.season }}-${{ inputs.week }}"
    )
    if writer_group not in text:
        errors.append(f"{source}: one shared repository/week writer lock is missing")
    if "cancel-in-progress: false" not in text:
        errors.append(f"{source}: production writers must serialize without cancellation")
    if "persist-credentials: false" not in text:
        errors.append(f"{source}: checkout credentials must not persist")
    if "clean: false" not in text:
        errors.append(f"{source}: durable production checkout must preserve operating state")
    if "python -m scripts.run_production_operation" not in text:
        errors.append(f"{source}: guarded production-operation entry point is missing")
    for adapter_argument in (
        '--weekly-config "${{ vars.CFB_V3_WEEKLY_CONFIG_FILE }}"',
        "--mode persist",
        "--confirmation EXECUTE_V3_OPERATION",
    ):
        if adapter_argument not in text:
            errors.append(
                f"{source}: production adapter argument is missing: {adapter_argument}"
            )
    if "python scripts/verify_repo_safety.py" not in text:
        errors.append(f"{source}: repository safety verification is missing")
    if text.count("actions/upload-artifact@v4") < 2 or "GITHUB_STEP_SUMMARY" not in text:
        errors.append(f"{source}: redacted failure artifact or job-summary logging is missing")
    if "guard-rejected:" not in text or "No checkout, credential access" not in text:
        errors.append(f"{source}: rejected authorization must fail visibly without secrets")
    if "CFB_V3_MODEL_NAME: epa_only" not in text:
        errors.append(f"{source}: EPA-only production model lock is missing")
    for operation in V3_PRODUCTION_OPERATIONS:
        if f"          - {operation}" not in text:
            errors.append(f"{source}: governed operation choice is missing: {operation}")
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

    v3_path = workflow_dir / V3_PRODUCTION_WORKFLOW
    errors.extend(
        v3_production_workflow_errors(
            v3_path.read_text(encoding="utf-8"),
            v3_path.name,
        )
    )

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
