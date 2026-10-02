from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEPLOY_PATH = ROOT / ".github" / "workflows" / "weekly-deploy.yml"
CI_PATH = ROOT / ".github" / "workflows" / "ci.yml"


def load(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8")
    return raw, yaml.safe_load(raw)


def test_deploy_workflow_is_manual_validation_and_pages_only():
    raw, workflow = load(DEPLOY_PATH)
    triggers = workflow.get("on", workflow.get(True, {}))

    assert "workflow_dispatch" in triggers
    assert "schedule" not in triggers
    assert set(workflow["jobs"]) == {"validate-and-deploy"}
    assert "./build/check.sh" in raw
    assert "actions/deploy-pages" in raw


def test_github_workflows_never_generate_or_mutate_monthly_content():
    deploy_raw, _ = load(DEPLOY_PATH)
    ci_raw, _ = load(CI_PATH)
    combined = deploy_raw + ci_raw

    for forbidden in (
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "generate_monthly.py",
        "build/collect.py",
        "git commit",
        "git push",
        "weekly-update:",
    ):
        assert forbidden not in combined


def test_ci_runs_navigation_and_site_link_quality_gate():
    raw, _ = load(CI_PATH)
    check = (ROOT / "build" / "check.sh").read_text(encoding="utf-8")

    assert "./build/check.sh" in raw
    assert "build/update_issue_navigation.py --check" in check
    assert "build/check_site_links.py" in check


def test_deploy_permissions_cannot_write_repository_contents():
    _, workflow = load(DEPLOY_PATH)

    assert workflow["permissions"]["contents"] == "read"
    assert workflow["permissions"]["pages"] == "write"
    assert workflow["permissions"]["id-token"] == "write"
