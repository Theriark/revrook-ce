"""Contract tests of the publishing workflows (2027 publishing contract).

The repository has three workflows: CI, Release candidate (prepare-rc.yml) and
Promote - Stage. The private publisher dispatches prepare-rc.yml and promote-stage.yml
by input name and finds a Stage run by its run name, so those are fixed here. The
tests read the workflow files only; nothing is executed and nothing needs a network.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
GROUP = "revrook-ce-delivery"
RUN_NAME = "publishing:${{ inputs.request_id }}"
STAGE_INPUTS = {
    "request_id",
    "version",
    "source_commit",
    "image",
    "development_run_id",
    "documentation_manifest_sha256",
    "rc_tag",
}
RC_KEYS = (
    "sourceCommit",
    "imageDigest",
    "developmentRunId",
    "workflowRunId",
    "documentationManifestSha256",
    "gateCycle",
)
DEVELOPMENT_JOB = "Deploy Development (build once, deploy the digest)"
RC_JOB = "Prepare RC (tag the tested Development image)"
PREPARE_RC_INPUTS = {
    "version",
    "source_commit",
    "image",
    "development_run_id",
    "documentation_manifest_sha256",
    "gate_cycle",
}


def load(name: str) -> dict[str, Any]:
    document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # YAML 1.1 reads the key `on` as the boolean True.
    document["on"] = document.pop(True, document.get("on"))
    return document  # type: ignore[no-any-return]


def text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def run_blocks(name: str) -> list[str]:
    blocks = []
    for job in load(name)["jobs"].values():
        blocks.extend(step["run"] for step in job["steps"] if "run" in step)
    return blocks


def test_the_workflow_set_is_ci_release_candidate_and_stage() -> None:
    names = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
    assert names == ["ci.yml", "prepare-rc.yml", "promote-stage.yml"]
    assert load("ci.yml")["name"] == "CI"
    assert load("prepare-rc.yml")["name"] == "Release candidate"
    assert load("promote-stage.yml")["name"] == "Promote - Stage"


def test_stage_takes_exactly_its_contract_inputs() -> None:
    triggers = load("promote-stage.yml")["on"]
    assert set(triggers) == {"workflow_dispatch"}
    declared = triggers["workflow_dispatch"]["inputs"]
    assert set(declared) == STAGE_INPUTS
    for definition in declared.values():
        assert definition["type"] == "string"
        assert definition["required"] is True


def test_a_stage_run_is_named_publishing_request_id() -> None:
    assert load("promote-stage.yml")["run-name"] == RUN_NAME


@pytest.mark.parametrize("name", sorted(path.name for path in WORKFLOWS.glob("*.yml")))
def test_every_deployment_run_shares_one_group_that_is_never_cancelled(
    name: str,
) -> None:
    concurrency = load(name)["concurrency"]
    if name == "ci.yml":
        # Pull request runs get their own cancellable group; every other event
        # shares the delivery group.
        expected = "${{ github.event_name == 'pull_request' }}"
        assert GROUP in concurrency["group"]
        assert concurrency["cancel-in-progress"] == expected
    else:
        assert concurrency == {"group": GROUP, "cancel-in-progress": False}


@pytest.mark.parametrize("name", sorted(path.name for path in WORKFLOWS.glob("*.yml")))
def test_no_workflow_writes_main_or_deploys_production(name: str) -> None:
    source = text(name)
    assert "heads/main" not in source
    environments = {job.get("environment") for job in load(name)["jobs"].values()}
    assert "production" not in environments


def test_stage_never_rebuilds_and_runs_in_the_stage_environment() -> None:
    source = text("promote-stage.yml")
    assert "build-push-action" not in source
    assert ":latest" not in source
    assert not re.search(r"docker\s+(buildx\s+)?build\b", source)
    assert "environment: stage" in source


@pytest.mark.parametrize("name", ["promote-stage.yml", "prepare-rc.yml"])
def test_inputs_reach_scripts_only_through_environment_variables(name: str) -> None:
    for block in run_blocks(name):
        assert "${{" not in block


def test_stage_deploys_the_registered_application_with_the_contract_labels() -> None:
    source = text("promote-stage.yml")
    assert "title: Stage ${{ env.SOURCE_SHA }}" in source
    assert "STAGE_APPLICATION_ID: 7QVBrkTn6rzEcICxV9GTj" in source
    assert "STAGE_HOST: ce-stg-revrook.theriark.dev" in source
    action = (ROOT / ".github/actions/dokploy-deploy/action.yml").read_text("utf-8")
    assert "revrook-ce GitHub Actions run ${GITHUB_RUN_ID}" in action
    # Verified before the first write, in this order.
    assert (
        source.index("Verify the image digest")
        < source.index("Verify the Development run")
        < source.index("Verify and consume the existing RC tag")
        < source.index("Confirm Development runs exactly this digest")
        < source.index("uses: ./.github/actions/dokploy-deploy")
        < source.index("Point the stage branch")
    )


def test_stage_consumes_the_existing_rc_and_never_writes_a_tag() -> None:
    source = text("promote-stage.yml")
    assert "RC_TAG: ${{ inputs.rc_tag }}" in source
    # Every RC key is verified, gateCycle included, and the RC-producing run is
    # checked on development, apart from this Stage run: a Release candidate run, or
    # a run of the former prepare-rc mode of CI for candidates made before it.
    for key in RC_KEYS:
        assert key in source
    assert '.head_branch == "development"' in source
    assert '.path == ".github/workflows/prepare-rc.yml"' in source
    assert RC_JOB in source
    # Read only: nothing creates, moves or deletes a tag or a release.
    assert 'git/tags"' not in source
    assert 'git/refs"' not in source
    assert "matching-refs" not in source
    assert "--method POST" not in source
    assert "--method DELETE" not in source
    assert "gh release" not in source
    assert "prefix=" not in source


def test_the_stage_branch_is_the_only_ref_that_stage_moves() -> None:
    source = text("promote-stage.yml")
    assert source.count("--method PATCH") == 1
    assert "git/refs/heads/stage" in source


def test_the_rc_is_prepared_by_its_own_workflow_on_development() -> None:
    workflow = load("prepare-rc.yml")
    assert set(workflow["on"]) == {"workflow_dispatch"}
    declared = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(declared) == PREPARE_RC_INPUTS
    for definition in declared.values():
        assert definition["type"] == "string"
        assert definition["required"] is True
    assert set(workflow["jobs"]) == {"prepare-rc"}
    job = workflow["jobs"]["prepare-rc"]
    assert job["name"] == RC_JOB
    assert job["if"] == "github.ref == 'refs/heads/development'"
    assert job["environment"] == "development"
    assert job["permissions"] == {
        "actions": "read",
        "contents": "write",
        "packages": "read",
    }
    # CI keeps the merge gate and the lock mode only.
    ci = load("ci.yml")
    ci_inputs = ci["on"]["workflow_dispatch"]["inputs"]
    assert set(ci_inputs) == {"mode"}
    assert ci_inputs["mode"]["options"] == ["ci", "lock"]
    assert "prepare-rc" not in ci["jobs"]
    assert "inputs.mode == 'ci'" in ci["jobs"]["detect"]["if"]
    assert "inputs.mode == 'ci'" in ci["jobs"]["gate"]["if"]


def test_prepare_rc_writes_a_tag_and_a_prerelease_and_nothing_else() -> None:
    job = load("prepare-rc.yml")["jobs"]["prepare-rc"]
    source = "\n".join(
        step.get("run", "") + step.get("uses", "") for step in job["steps"]
    )
    for key in RC_KEYS:
        assert key in source
    assert 'prefix="v${BASE_VERSION}-rc."' in source
    assert "--argjson cycle" in source
    assert "--argjson run" in source
    assert "git/tags" in source
    assert "--verify-tag --prerelease" in source
    # Reconcile first; no rebuild, no deployment, no Stage or main write.
    assert "Reconcile first" in source
    assert "build-push-action" not in source
    assert "dokploy-deploy" not in source
    assert "heads/stage" not in source
    assert "--latest" not in source
    assert "--method PATCH" not in source


def test_the_job_names_that_other_workflows_grep_for_exist() -> None:
    names = {key: value["name"] for key, value in load("ci.yml")["jobs"].items()}
    assert names["deploy-development"] == DEVELOPMENT_JOB
    assert load("prepare-rc.yml")["jobs"]["prepare-rc"]["name"] == RC_JOB
    assert RC_JOB in text("promote-stage.yml")
    assert DEVELOPMENT_JOB in text("promote-stage.yml")
    assert DEVELOPMENT_JOB in text("prepare-rc.yml")


def test_every_action_is_pinned_to_a_full_commit_sha() -> None:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.search(r"uses:\s*(\S+)", line)
            if match and not match.group(1).startswith("./"):
                assert re.search(r"@[0-9a-f]{40}$", match.group(1)), (path.name, line)


@pytest.mark.parametrize("name", sorted(path.name for path in WORKFLOWS.glob("*.yml")))
def test_every_script_is_valid_bash(name: str, tmp_path: Path) -> None:
    for index, block in enumerate(run_blocks(name)):
        script = tmp_path / f"{name}-{index}.sh"
        script.write_text(re.sub(r"\$\{\{.*?\}\}", "EXPR", block), encoding="utf-8")
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, (name, index, result.stderr)
