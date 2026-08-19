from pathlib import Path

import pytest

from scripts.verify_repo_safety import (
    PRODUCTION_REPOSITORY,
    V3_PRODUCTION_OPERATIONS,
    ci_workflow_errors,
    production_workflow_errors,
    repository_errors,
    requirement_errors,
    v3_production_workflow_errors,
)


ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_repository_safety_controls_pass():
    assert repository_errors(ROOT) == []


@pytest.mark.parametrize(
    ("unsafe_line", "expected_fragment"),
    [
        ("requests", "not exactly pinned"),
        ("requests>=2", "not exactly pinned"),
        ("pytest~=9.1", "not exactly pinned"),
        ("-r requirements-unlocked.txt", "include is not allowed"),
    ],
)
def test_requirement_validator_rejects_non_exact_versions(unsafe_line, expected_fragment):
    errors = requirement_errors(f"{unsafe_line}\n", "requirements.txt")
    assert any(expected_fragment in error for error in errors)


def _safe_production_workflow() -> str:
    return f"""on:
  workflow_dispatch:
concurrency:
  group: production-test
  cancel-in-progress: false
permissions:
  contents: read
jobs:
  test:
    if: github.repository == '{PRODUCTION_REPOSITORY}'
    steps:
      - run: python -m pip install --requirement requirements.txt
"""


def test_production_workflow_validator_accepts_inert_v3_configuration():
    assert production_workflow_errors(_safe_production_workflow(), "workflow.yml") == []


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda text: text.replace("  workflow_dispatch:\n", "  schedule:\n"), "schedule trigger"),
        (
            lambda text: text.replace(PRODUCTION_REPOSITORY, "JCRABURN/cfb-betting-system-v3"),
            "allow-list guard",
        ),
        (lambda text: text.replace("concurrency:\n", ""), "concurrency control"),
        (lambda text: text.replace("cancel-in-progress: false", "cancel-in-progress: true"), "serialize"),
        (lambda text: text.replace("contents: read", "contents: write"), "read-only"),
    ],
)
def test_production_workflow_validator_rejects_unsafe_changes(mutator, expected_fragment):
    errors = production_workflow_errors(mutator(_safe_production_workflow()), "workflow.yml")
    assert any(expected_fragment in error for error in errors)


def _safe_ci_workflow() -> str:
    return """on:
  pull_request:
concurrency:
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  test:
    steps:
      - run: python -m pip install --requirement requirements-dev.txt
      - run: python scripts/verify_repo_safety.py
      - run: python -m scripts.verify_migrations
      - run: python -m pytest -q
"""


def test_ci_validator_accepts_read_only_secretless_pull_request_ci():
    assert ci_workflow_errors(_safe_ci_workflow()) == []


@pytest.mark.parametrize(
    ("unsafe_change", "expected_fragment"),
    [
        ("  schedule:\n", "pull-request-only"),
        ("  workflow_dispatch:\n", "pull-request-only"),
        ("  pull_request_target:\n", "pull_request_target is forbidden"),
        ("      token: ${{ secrets.DEPLOY_TOKEN }}\n", "must not receive repository secrets"),
    ],
)
def test_ci_validator_rejects_unsafe_triggers_and_secrets(unsafe_change, expected_fragment):
    text = _safe_ci_workflow().replace("jobs:\n", f"{unsafe_change}jobs:\n")
    errors = ci_workflow_errors(text)
    assert any(expected_fragment in error for error in errors)


def test_ci_validator_rejects_job_level_write_permissions():
    text = _safe_ci_workflow().replace("  test:\n", "  test:\n    permissions:\n      contents: write\n")
    errors = ci_workflow_errors(text)
    assert any("must not grant write permissions" in error for error in errors)


def test_ci_validator_requires_disposable_copy_migration_verification():
    text = _safe_ci_workflow().replace("      - run: python -m scripts.verify_migrations\n", "")
    errors = ci_workflow_errors(text)
    assert any("does not verify migrations" in error for error in errors)


def _safe_v3_production_workflow() -> str:
    return """on:
  workflow_dispatch:
    inputs:
      operation:
        options:
          - tuesday_lock
          - wednesday_refresh
          - thursday_refresh
          - friday_refresh
          - saturday_final
          - postgame_grading
          - weekly_audit
concurrency:
  group: v3-production-writer-${{ github.repository }}-${{ inputs.season }}-${{ inputs.week }}
  cancel-in-progress: false
permissions:
  contents: read
jobs:
  guard-rejected:
    steps:
      - run: echo "No checkout, credential access" >> "$GITHUB_STEP_SUMMARY"
  guarded:
    if: >-
      github.repository == 'JCRABURN/cfb-betting-system-v3' &&
      vars.CFB_V3_PRODUCTION_ENABLED == 'true' &&
      vars.CFB_V3_OPERATION_EXECUTION_ENABLED == 'true' &&
      vars.CFB_V3_KILL_SWITCH == 'false' &&
      vars.CFB_V3_OWNER_CUTOVER_APPROVED == 'true' &&
      inputs.confirmation == 'RUN_V3_OPERATION'
    environment: v3-production
    permissions:
      contents: read
    env:
      CFB_V3_MODEL_NAME: epa_only
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - run: python scripts/verify_repo_safety.py
      - run: python -m scripts.run_production_operation
      - uses: actions/upload-artifact@v4
      - run: echo result >> "$GITHUB_STEP_SUMMARY"
"""


def test_v3_production_workflow_validator_accepts_manual_fail_closed_gateway():
    assert v3_production_workflow_errors(_safe_v3_production_workflow()) == []


def test_v3_workflow_and_runtime_operation_sets_match():
    from operations.config import PRODUCTION_OPERATIONS

    assert V3_PRODUCTION_OPERATIONS == PRODUCTION_OPERATIONS


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda text: text.replace("  workflow_dispatch:\n", "  schedule:\n"), "schedule"),
        (
            lambda text: text.replace(
                "JCRABURN/cfb-betting-system-v3",
                "JCRABURN/cfb-betting-system",
            ),
            "allow-list",
        ),
        (
            lambda text: text.replace("vars.CFB_V3_KILL_SWITCH == 'false' &&\n", ""),
            "CFB_V3_KILL_SWITCH",
        ),
        (
            lambda text: text.replace("contents: read", "contents: write"),
            "write permissions",
        ),
        (
            lambda text: text.replace("cancel-in-progress: false", "cancel-in-progress: true"),
            "serialize",
        ),
        (
            lambda text: text.replace("          - weekly_audit\n", ""),
            "weekly_audit",
        ),
    ],
)
def test_v3_production_workflow_validator_rejects_unsafe_changes(
    mutator,
    expected_fragment,
):
    errors = v3_production_workflow_errors(mutator(_safe_v3_production_workflow()))
    assert any(expected_fragment in error for error in errors)
