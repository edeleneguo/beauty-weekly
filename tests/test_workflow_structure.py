#!/usr/bin/env python3
"""Static structural tests for weekly-deploy.yml workflow.

Ensures the deploy workflow meets atomicity, ordering, and safety invariants:
  - No deploy_pages.py (non-atomic API-per-file approach removed)
  - Intentional-failure gate exists before any mutation
  - No git commit/push before the gate
  - YAML is syntactically valid
  - Required steps present in correct order

Run: python3 -m pytest tests/test_workflow_structure.py -v
"""

from __future__ import annotations

import os
import re

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")


@pytest.fixture(scope="module")
def workflow_raw() -> str:
    with open(WORKFLOW_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def workflow_dict(workflow_raw: str) -> dict:
    return yaml.safe_load(workflow_raw)


@pytest.fixture(scope="module")
def step_names(workflow_dict: dict) -> list[str]:
    """Extract ordered list of step names from the generate-and-deploy job."""
    jobs = workflow_dict.get("jobs", {})
    job = jobs.get("generate-and-deploy", {})
    steps = job.get("steps", [])
    return [s.get("name", "") for s in steps]


class TestYAMLSyntax:
    """Workflow YAML must be syntactically valid."""

    def test_valid_yaml(self, workflow_raw: str):
        data = yaml.safe_load(workflow_raw)
        assert isinstance(data, dict), "Top-level YAML must be a mapping"

    def test_has_jobs(self, workflow_dict: dict):
        assert "jobs" in workflow_dict, "Workflow must define jobs"

    def test_has_generate_and_deploy_job(self, workflow_dict: dict):
        assert "generate-and-deploy" in workflow_dict["jobs"]


class TestNoDeployPagesScript:
    """deploy_pages.py must not be referenced anywhere in the workflow.

    The non-atomic per-file API upload approach has been replaced by
    atomic git commit + push.
    """

    def test_no_deploy_pages_reference(self, workflow_raw: str):
        assert "deploy_pages.py" not in workflow_raw, (
            "weekly-deploy.yml still references deploy_pages.py — "
            "the non-atomic per-file upload approach must be removed"
        )


class TestIntentionalFailureGate:
    """Intentional-failure gate must exist and be before any mutation."""

    def test_has_intentional_failure_input(self, workflow_dict: dict):
        # PyYAML parses bare 'on' as boolean True
        triggers = workflow_dict.get("on", workflow_dict.get(True, {}))
        dispatch = triggers.get("workflow_dispatch", {})
        inputs = dispatch.get("inputs", {})
        assert "intentional_failure" in inputs, (
            "workflow_dispatch must have intentional_failure input"
        )
        assert inputs["intentional_failure"].get("type") == "boolean"

    def test_has_gate_step(self, step_names: list[str]):
        gate_steps = [n for n in step_names if "intentional failure" in n.lower()]
        assert len(gate_steps) >= 1, "Workflow must have an intentional-failure gate step"

    def test_gate_exits_with_error(self, workflow_raw: str):
        gate_match = re.search(
            r"Gate.*Intentional failure.*?(?=\n      - name:|\Z)",
            workflow_raw,
            re.DOTALL | re.IGNORECASE,
        )
        assert gate_match, "Gate step block not found"
        block = gate_match.group()
        assert "exit 1" in block, "Gate step must call exit 1 to abort"

    def test_gate_before_stage2_generation(self, step_names: list[str]):
        gate_idx = None
        gen_idx = None
        for i, name in enumerate(step_names):
            if "intentional failure" in name.lower() and gate_idx is None:
                gate_idx = i
            if "generate" in name.lower() and "canonical" in name.lower() and gen_idx is None:
                gen_idx = i
        assert gate_idx is not None, "Gate step not found"
        assert gen_idx is not None, "Stage 2 generate step not found"
        assert gate_idx < gen_idx, (
            f"Gate (step {gate_idx}) must come before Stage 2 generation (step {gen_idx})"
        )

    def test_gate_before_git_commit(self, step_names: list[str]):
        gate_idx = None
        commit_idx = None
        for i, name in enumerate(step_names):
            if "intentional failure" in name.lower() and gate_idx is None:
                gate_idx = i
            if "commit" in name.lower() and "git" not in name.lower() and commit_idx is None:
                commit_idx = i
            if ("atomic" in name.lower() or "push" in name.lower()) and commit_idx is None:
                commit_idx = i
        if gate_idx is not None and commit_idx is not None:
            assert gate_idx < commit_idx, (
                f"Gate (step {gate_idx}) must come before commit/push (step {commit_idx})"
            )


class TestAtomicCommitPush:
    """Single atomic commit+push step must exist after the gate."""

    def test_has_atomic_step(self, step_names: list[str]):
        atomic_steps = [
            n
            for n in step_names
            if "atomic" in n.lower() or ("commit" in n.lower() and "push" in n.lower())
        ]
        assert len(atomic_steps) >= 1, "Workflow must have an atomic commit+push step"

    def test_push_uses_safe_rebase(self, workflow_raw: str):
        assert "git rebase" in workflow_raw or "git pull --rebase" in workflow_raw, (
            "Push step must use safe rebase handling"
        )

    def test_single_git_commit(self, workflow_raw: str):
        """There should be exactly one 'git commit' call (atomic)."""
        commits = re.findall(r"git commit\b", workflow_raw)
        assert len(commits) == 1, (
            f"Expected exactly 1 git commit call, found {len(commits)} — "
            "all files must go into a single atomic commit"
        )


class TestStepOrdering:
    """Required steps must appear in the correct logical order."""

    def test_collect_before_generate(self, step_names: list[str]):
        collect_idx = None
        generate_idx = None
        for i, n in enumerate(step_names):
            if "collect" in n.lower() and collect_idx is None:
                collect_idx = i
            if "generate" in n.lower() and "canonical" in n.lower() and generate_idx is None:
                generate_idx = i
        if collect_idx is not None and generate_idx is not None:
            assert collect_idx < generate_idx

    def test_validate_before_render(self, step_names: list[str]):
        validate_idx = None
        render_idx = None
        for i, n in enumerate(step_names):
            if "validate" in n.lower() and validate_idx is None:
                validate_idx = i
            if "render" in n.lower() and render_idx is None:
                render_idx = i
        if validate_idx is not None and render_idx is not None:
            assert validate_idx <= render_idx

    def test_gate_before_stage2_generation(self, step_names: list[str]):
        gate_idx = None
        gen_idx = None
        for i, n in enumerate(step_names):
            if "intentional failure" in n.lower() and gate_idx is None:
                gate_idx = i
            if "generate" in n.lower() and "canonical" in n.lower() and gen_idx is None:
                gen_idx = i
        assert gate_idx is not None, "Gate step not found in step list"
        assert gen_idx is not None, "Stage 2 generation step not found"
        assert gate_idx < gen_idx, (
            f"Gate (step {gate_idx}) must precede Stage 2 generation (step {gen_idx})"
        )

    def test_gate_before_manifest(self, step_names: list[str]):
        gate_idx = None
        commit_idx = None
        for i, n in enumerate(step_names):
            if "intentional failure" in n.lower() and gate_idx is None:
                gate_idx = i
            if "atomic" in n.lower() and commit_idx is None:
                commit_idx = i
        if gate_idx is not None and commit_idx is not None:
            assert gate_idx < commit_idx

    def test_build_wait_before_verify(self, step_names: list[str]):
        build_idx = None
        verify_idx = None
        for i, n in enumerate(step_names):
            if (
                ("pages" in n.lower() or "build" in n.lower())
                and "wait" in n.lower()
                and build_idx is None
            ):
                build_idx = i
            if (
                "verify live" in n.lower() or "verify deployment" in n.lower()
            ) and verify_idx is None:
                verify_idx = i
        if build_idx is not None and verify_idx is not None:
            assert build_idx < verify_idx

    def test_commit_before_build_wait(self, step_names: list[str]):
        commit_idx = None
        build_idx = None
        for i, n in enumerate(step_names):
            if "atomic" in n.lower() and commit_idx is None:
                commit_idx = i
            if (
                ("pages" in n.lower() or "build" in n.lower())
                and "wait" in n.lower()
                and build_idx is None
            ):
                build_idx = i
        if commit_idx is not None and build_idx is not None:
            assert commit_idx < build_idx, "Commit+push must happen before waiting for Pages build"


class TestNoMutationBeforeGate:
    """No git add, commit, push, or API deploy must appear before the gate step."""

    def test_no_git_add_before_gate(self, workflow_raw: str):
        gate_pos = workflow_raw.find("Intentional failure")
        assert gate_pos > 0, "Gate step not found"
        before_gate = workflow_raw[:gate_pos]
        assert "git add" not in before_gate, (
            "git add must not appear before the intentional-failure gate"
        )

    def test_no_git_commit_before_gate(self, workflow_raw: str):
        gate_pos = workflow_raw.find("Intentional failure")
        before_gate = workflow_raw[:gate_pos]
        assert "git commit" not in before_gate, (
            "git commit must not appear before the intentional-failure gate"
        )

    def test_no_git_push_before_gate(self, workflow_raw: str):
        gate_pos = workflow_raw.find("Intentional failure")
        before_gate = workflow_raw[:gate_pos]
        assert "git push" not in before_gate, (
            "git push must not appear before the intentional-failure gate"
        )

    def test_no_contents_api_upload(self, workflow_raw: str):
        assert "/contents/" not in workflow_raw, (
            "GitHub Contents API upload (/contents/) must not be used — "
            "use atomic git commit instead"
        )

    def test_no_llm_generation_before_gate(self, workflow_raw: str):
        gate_pos = workflow_raw.find("Intentional failure")
        assert gate_pos > 0, "Gate step not found"
        before_gate = workflow_raw[:gate_pos]
        assert "generate_monthly" not in before_gate, (
            "LLM generation (generate_monthly) must not appear before the intentional-failure gate"
        )

    def test_no_manifest_before_gate(self, workflow_raw: str):
        gate_pos = workflow_raw.find("Intentional failure")
        before_gate = workflow_raw[:gate_pos]
        assert "deploy-manifest" not in before_gate, (
            "Manifest generation must not appear before the intentional-failure gate"
        )


class TestWeekPropagation:
    """Month resolution must not depend on inputs.* being non-null on schedule."""

    def test_does_not_use_inputs_directly_in_bash(self, workflow_raw: str):
        """inputs.target_month should be passed via env, not inline in bash."""
        gate_block = re.search(
            r"Gate.*?(?=\n      - name:|\Z)",
            workflow_raw,
            re.DOTALL,
        )
        if gate_block:
            block = gate_block.group()
            assert "${{ inputs.target_month }}" not in block, (
                "Gate step must not reference inputs.target_month directly in bash "
                "(it is null on schedule). Use GITHUB_OUTPUT env var instead."
            )

    def test_month_validates_format(self, workflow_raw: str):
        """Month format must be validated (YYYY-MM)."""
        assert re.search(r"\[0-9\]\{4\}", workflow_raw), (
            "Month format validation regex not found in workflow"
        )


class TestManifestWeekEnv:
    """Generate artifact manifest step must receive MONTH via step env, not rely on shell var."""

    def test_manifest_step_has_month_env(self, workflow_dict: dict):
        steps = workflow_dict["jobs"]["generate-and-deploy"]["steps"]
        manifest_step = None
        for s in steps:
            if s.get("id") == "manifest" or (
                "manifest" in s.get("name", "").lower() and "generate" in s.get("name", "").lower()
            ):
                manifest_step = s
                break
        assert manifest_step is not None, "Generate artifact manifest step not found"
        env = manifest_step.get("env", {})
        assert "MONTH" in env, (
            "Manifest step must declare env.MONTH so Python can access os.environ['MONTH']"
        )
        assert env["MONTH"] == "${{ steps.target_month.outputs.month }}", (
            "env.MONTH must be sourced from steps.target_month.outputs.month"
        )


class TestAtomicCommitGITHUB_TOKEN:
    """Atomic commit step must declare env GITHUB_TOKEN from secrets.GITHUB_TOKEN."""

    def test_atomic_commit_has_github_token_env(self, workflow_dict: dict):
        steps = workflow_dict["jobs"]["generate-and-deploy"]["steps"]
        atomic_step = None
        for s in steps:
            name = s.get("name", "").lower()
            if "atomic" in name or ("commit" in name and "push" in name):
                atomic_step = s
                break
        assert atomic_step is not None, "Atomic commit and push step not found"
        env = atomic_step.get("env", {})
        assert "GITHUB_TOKEN" in env, "Atomic commit step must declare env.GITHUB_TOKEN"
        assert env["GITHUB_TOKEN"] == "${{ secrets.GITHUB_TOKEN }}", (
            "env.GITHUB_TOKEN must be sourced from secrets.GITHUB_TOKEN"
        )


class TestPagesBuildWait:
    """Workflow must poll/wait for GitHub Pages build before verification."""

    def test_has_pages_build_wait(self, step_names: list[str]):
        wait_steps = [
            n
            for n in step_names
            if ("wait" in n.lower() or "poll" in n.lower())
            and ("pages" in n.lower() or "build" in n.lower())
        ]
        assert len(wait_steps) >= 1, (
            "Workflow must have a step that waits/polls for GitHub Pages build"
        )

    def test_polls_build_status(self, workflow_raw: str):
        assert "pages/builds" in workflow_raw, (
            "Workflow must poll GitHub Pages build status via /pages/builds API"
        )


CI_WORKFLOW_PATH = os.path.join(ROOT, ".github", "workflows", "ci.yml")
DEPLOY_WORKFLOW_PATH = os.path.join(ROOT, ".github", "workflows", "weekly-deploy.yml")


class TestCIBaselineWeek:
    """CI quality gate must pin a known-good canonical fixture week."""

    @pytest.fixture(scope="class")
    def ci_workflow_raw(self) -> str:
        with open(CI_WORKFLOW_PATH, encoding="utf-8") as f:
            return f.read()

    def test_ci_has_w28_baseline(self, ci_workflow_raw: str):
        assert "BEAUTY_WEEKLY_WEEK: 2026-W28" in ci_workflow_raw, (
            "ci job must set BEAUTY_WEEKLY_WEEK=2026-W28 for the quality gate"
        )

    def test_ci_has_historical_fixture_flag(self, ci_workflow_raw: str):
        assert "BEAUTY_WEEKLY_HISTORICAL_FIXTURE: 1" in ci_workflow_raw, (
            "ci job must set BEAUTY_WEEKLY_HISTORICAL_FIXTURE=1 for the quality gate"
        )

    def test_monthly_deploy_no_historical_fixture_flag(self):
        with open(DEPLOY_WORKFLOW_PATH, encoding="utf-8") as f:
            deploy_raw = f.read()
        assert "BEAUTY_WEEKLY_HISTORICAL_FIXTURE" not in deploy_raw, (
            "monthly-deploy must not set BEAUTY_WEEKLY_HISTORICAL_FIXTURE"
        )

    def test_monthly_deploy_no_hardcoded_w28(self):
        with open(DEPLOY_WORKFLOW_PATH, encoding="utf-8") as f:
            deploy_raw = f.read()
        assert "2026-W28" not in deploy_raw, (
            "monthly-deploy must not hardcode 2026-W28; it must validate the target week"
        )


class TestVerification:
    """Verification must check both ISO week and SHA256 hash."""

    def test_verifies_week_number(self, workflow_raw: str):
        assert re.search(r"month_ok|month_num|target_month", workflow_raw), (
            "Verification must compare actual vs expected month number"
        )

    def test_verifies_sha256(self, workflow_raw: str):
        assert "sha256" in workflow_raw.lower(), (
            "Verification must check SHA256 hash of live content"
        )

    def test_checks_raw_and_cdn(self, workflow_raw: str):
        assert "raw.githubusercontent.com" in workflow_raw, (
            "Verification must check GitHub Raw content"
        )
        assert "github.io" in workflow_raw or "cdn" in workflow_raw.lower(), (
            "Verification must check CDN/live content"
        )
