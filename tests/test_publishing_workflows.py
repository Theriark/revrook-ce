"""Contract tests of the publishing workflows (2027 publishing contract).

The private publisher dispatches promote-stage.yml and finalize-release.yml by input
name and finds the run by its run name, so both are fixed here. The tests read the
workflow files only; nothing is executed and nothing needs a network.
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
}
FINALIZE_INPUTS = STAGE_INPUTS | {"stage_promotion_run_id", "rc_tag"}


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


def test_the_workflow_set_is_ci_stage_finalize_and_production() -> None:
    names = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
    assert names == [
        "ci.yml",
        "finalize-release.yml",
        "promote-production.yml",
        "promote-stage.yml",
    ]


@pytest.mark.parametrize(
    ("name", "inputs"),
    [("promote-stage.yml", STAGE_INPUTS), ("finalize-release.yml", FINALIZE_INPUTS)],
)
def test_a_publishing_workflow_takes_exactly_its_contract_inputs(
    name: str, inputs: set[str]
) -> None:
    triggers = load(name)["on"]
    assert set(triggers) == {"workflow_dispatch"}
    declared = triggers["workflow_dispatch"]["inputs"]
    assert set(declared) == inputs
    for definition in declared.values():
        assert definition["type"] == "string"
        assert definition["required"] is True


@pytest.mark.parametrize("name", ["promote-stage.yml", "finalize-release.yml"])
def test_a_publishing_run_is_named_publishing_request_id(name: str) -> None:
    assert load(name)["run-name"] == RUN_NAME


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


def test_production_stays_disabled_and_closed() -> None:
    workflow = load("promote-production.yml")
    assert workflow["env"]["PRODUCTION_ENABLED"] == "false"
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["jobs"]["promote"]["needs"] == "guard"
    assert 'PRODUCTION_ENABLED}" != "true"' in text("promote-production.yml")
    # Nothing but the production recipe may write to main.
    assert "heads/main" not in text("promote-stage.yml")
    assert "heads/main" not in text("finalize-release.yml")


@pytest.mark.parametrize("name", ["promote-stage.yml", "finalize-release.yml"])
def test_a_publishing_workflow_never_rebuilds_or_deploys_production(
    name: str,
) -> None:
    source = text(name)
    assert "build-push-action" not in source
    assert ":latest" not in source
    assert not re.search(r"docker\s+(buildx\s+)?build\b", source)
    environments = {job.get("environment") for job in load(name)["jobs"].values()}
    assert "production" not in environments
    assert "environment: stage" in source


@pytest.mark.parametrize("name", ["promote-stage.yml", "finalize-release.yml"])
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
        < source.index("uses: ./.github/actions/dokploy-deploy")
        < source.index("Create or reuse the annotated RC tag")
        < source.index("Point the stage branch")
    )


def test_the_rc_tag_is_annotated_json_with_the_contract_keys() -> None:
    source = text("promote-stage.yml")
    for key in (
        "sourceCommit",
        "imageDigest",
        "developmentRunId",
        "workflowRunId",
        "documentationManifestSha256",
    ):
        assert key in source
    assert 'prefix="v${BASE_VERSION}-rc."' in source
    assert "--argjson dev" in source
    assert "--argjson run" in source
    assert "git/tags" in source


def test_the_stable_tag_adds_the_stage_run_and_the_rc_tag() -> None:
    source = text("finalize-release.yml")
    for key in ("stagePromotionRunId", "rcTag", "workflowRunId"):
        assert key in source
    assert "--verify-tag" in source
    assert ".draft == false and .prerelease == false" in source
    assert "Reconcile first" in source


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
