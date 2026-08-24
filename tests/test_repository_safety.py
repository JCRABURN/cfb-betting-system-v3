from pathlib import Path

import pytest

from scripts.verify_repo_safety import (
    PRODUCTION_REPOSITORY,
    V3_PRODUCTION_OPERATIONS,
    ci_workflow_errors,
    production_workflow_errors,
    repository_errors,
    requirement_errors,
    v3_cloud_setup_workflow_errors,
    v3_production_workflow_errors,
    v3_shadow_rehearsal_workflow_errors,
)


ROOT = Path(__file__).resolve().parents[1]


def test_checked_in_repository_safety_controls_pass():
    assert repository_errors(ROOT) == []


def test_every_production_stage_is_cloud_hosted_and_only_v3_production_is_scheduled():
    workflow_directory = ROOT / ".github" / "workflows"
    operation_text = (workflow_directory / "v3_production_operations.yml").read_text(
        encoding="utf-8"
    )
    assert "runs-on: ubuntu-latest" in operation_text
    assert "self-hosted" not in operation_text
    assert "\n  schedule:" in operation_text
    assert "- cron: '7,22,37,52 * * * 1-6'" in operation_text
    assert "python -m scripts.resolve_production_schedule" in operation_text
    assert "python -m scripts.run_cloud_production_operation" in operation_text
    assert "--capture-provider-data" in operation_text
    for operation in V3_PRODUCTION_OPERATIONS:
        assert f"          - {operation}" in operation_text
    for workflow in workflow_directory.glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "self-hosted" not in text
        if workflow.name != "v3_production_operations.yml":
            assert "\n  schedule:" not in text


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


def test_requirement_validator_accepts_exactly_pinned_binary_extra():
    assert requirement_errors("psycopg[binary]==3.3.4\n", "requirements.txt") == []


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
      - run: python -m scripts.verify_cloud_migrations
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
  schedule:
    - cron: '7,22,37,52 * * * 1-6'
  workflow_dispatch:
    inputs:
      operation:
        options:
          - tuesday_lock
          - wednesday_refresh
          - thursday_refresh
          - friday_refresh
          - saturday_final
          - sportsbook_refresh
          - postgame_grading
          - weekly_audit
concurrency:
  group: v3-production-writer-${{ github.repository }}
  cancel-in-progress: false
permissions:
  contents: read
jobs:
  guard-rejected:
    steps:
      - run: echo "No checkout, credential access" >> "$GITHUB_STEP_SUMMARY"
  resolve-operation:
    steps:
      - run: python -m scripts.resolve_production_schedule
  idle-heartbeat:
    steps:
      - run: echo idle
  guarded:
    if: >-
      needs.resolve-operation.outputs.should-run == 'true' &&
      github.repository == 'JCRABURN/cfb-betting-system-v3' &&
      vars.CFB_V3_PRODUCTION_ENABLED == 'true' &&
      vars.CFB_V3_OPERATION_EXECUTION_ENABLED == 'true' &&
      vars.CFB_V3_KILL_SWITCH == 'false' &&
      vars.CFB_V3_OWNER_CUTOVER_APPROVED == 'true' &&
      vars.CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED == 'true' &&
      github.event_name == 'schedule' &&
      inputs.confirmation == 'RUN_V3_OPERATION'
    environment: v3-production
    runs-on: ubuntu-latest
    permissions:
      contents: read
    env:
      CFB_V3_MODEL_NAME: epa_only
      CFB_V3_OPERATION_INSTANCE: ${{ needs.resolve-operation.outputs.operation-instance }}
      CFB_V3_PERSISTENCE_BACKEND: managed_postgresql
      CFB_V3_DATABASE_URL: ${{ secrets.CFB_V3_DATABASE_URL }}
    steps:
      - uses: actions/checkout@v4
        with:
          clean: true
          persist-credentials: false
      - run: python scripts/verify_repo_safety.py
      - run: python -m scripts.run_cloud_production_operation
        --weekly-config "${{ vars.CFB_V3_WEEKLY_CONFIG_FILE }}"
        --confirmation EXECUTE_V3_CLOUD_OPERATION
        --capture-provider-data
        --provider-confirmation CAPTURE_V3_PROVIDER_PAYLOADS
      - uses: actions/upload-artifact@v4
      - uses: actions/upload-artifact@v4
      - uses: actions/upload-artifact@v4
      - run: echo result >> "$GITHUB_STEP_SUMMARY"
"""


def test_v3_production_workflow_validator_accepts_scheduled_fail_closed_gateway():
    assert v3_production_workflow_errors(_safe_v3_production_workflow()) == []


def test_v3_workflow_and_runtime_operation_sets_match():
    from operations.config import PRODUCTION_OPERATIONS

    assert V3_PRODUCTION_OPERATIONS == PRODUCTION_OPERATIONS


@pytest.mark.parametrize(
    ("mutator", "expected_fragment"),
    [
        (lambda text: text.replace("  schedule:\n", "  disabled_schedule:\n"), "schedule"),
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
        (
            lambda text: text.replace("        --confirmation EXECUTE_V3_CLOUD_OPERATION\n", ""),
            "EXECUTE_V3_CLOUD_OPERATION",
        ),
        (
            lambda text: text.replace("    runs-on: ubuntu-latest\n", ""),
            "GitHub-hosted runner",
        ),
        (
            lambda text: text.replace("          clean: true\n", ""),
            "start clean",
        ),
        (lambda text: text + "# self-hosted\n", "self-hosted runners are forbidden"),
    ],
)
def test_v3_production_workflow_validator_rejects_unsafe_changes(
    mutator,
    expected_fragment,
):
    errors = v3_production_workflow_errors(mutator(_safe_v3_production_workflow()))
    assert any(expected_fragment in error for error in errors)


def _safe_cloud_setup_workflow() -> str:
    return """on:
  workflow_dispatch:
jobs:
  rejected:
    steps:
      - run: echo rejected
  setup:
    if: >-
      github.repository == 'JCRABURN/cfb-betting-system-v3' &&
      vars.CFB_V3_OWNER_CUTOVER_APPROVED == 'true' &&
      vars.CFB_V3_KILL_SWITCH == 'true' &&
      vars.CFB_V3_PRODUCTION_ENABLED == 'false' &&
      vars.CFB_V3_OPERATION_EXECUTION_ENABLED == 'false' &&
      inputs.confirmation == 'INITIALIZE_V3_CLOUD_STATE'
    environment: v3-production
    runs-on: ubuntu-latest
    env:
      CFB_V3_DATABASE_URL: ${{ secrets.CFB_V3_DATABASE_URL }}
    steps:
      - uses: actions/checkout@v4
        with:
          clean: true
          persist-credentials: false
      - run: python scripts/verify_repo_safety.py
      - run: python -m scripts.prepare_cloud_database
        --confirmation INITIALIZE_V3_CLOUD_STATE
      - uses: actions/upload-artifact@v4
"""


def test_cloud_setup_workflow_is_manual_guarded_and_github_hosted():
    assert v3_cloud_setup_workflow_errors(_safe_cloud_setup_workflow()) == []


@pytest.mark.parametrize(
    ("needle", "expected"),
    [
        ("  workflow_dispatch:\n", "controlled manual dispatch"),
        ("    runs-on: ubuntu-latest\n", "GitHub-hosted"),
        ("      CFB_V3_DATABASE_URL: ${{ secrets.CFB_V3_DATABASE_URL }}\n", "secret"),
        ("        --confirmation INITIALIZE_V3_CLOUD_STATE\n", "confirmation"),
    ],
)
def test_cloud_setup_workflow_rejects_missing_controls(needle, expected):
    errors = v3_cloud_setup_workflow_errors(
        _safe_cloud_setup_workflow().replace(needle, "")
    )
    assert any(expected in error for error in errors)


def test_shadow_workflow_is_manual_isolated_and_github_hosted():
    text = (ROOT / ".github" / "workflows" / "v3_shadow_rehearsal.yml").read_text(
        encoding="utf-8"
    )
    assert v3_shadow_rehearsal_workflow_errors(text) == []


@pytest.mark.parametrize(
    ("needle", "expected"),
    [
        ("  workflow_dispatch:\n", "manual dispatch"),
        ("vars.CFB_V3_PRODUCTION_ENABLED == 'false'", "PRODUCTION_ENABLED"),
        ("vars.CFB_V3_SHADOW_REHEARSAL_ENABLED == 'true'", "SHADOW_REHEARSAL_ENABLED"),
        ("--confirmation EXECUTE_V3_CLOUD_SHADOW_REHEARSAL", "SHADOW_REHEARSAL"),
        ("          - weekly_audit\n", "weekly_audit"),
    ],
)
def test_shadow_workflow_validator_rejects_missing_controls(needle, expected):
    text = (ROOT / ".github" / "workflows" / "v3_shadow_rehearsal.yml").read_text(
        encoding="utf-8"
    )
    errors = v3_shadow_rehearsal_workflow_errors(text.replace(needle, ""))
    assert any(expected in error for error in errors)
