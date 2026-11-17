"""Contract tests of the delivery workflows (release standard, one button each).

The repository has three workflows: CI, Promote - Stage and Release. Gate 2 dispatches
promote-stage.yml and Gate 3 dispatches release.yml, both on development with no
inputs, so each takes only the optional boolean dry_run. No workflow moves the stage
or main branch: the gate script does that with the operator token. The tests read the
workflow files and run the release tag script on throwaway git repositories; nothing
is dispatched and nothing needs a network.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
TAGS_SCRIPT = ROOT / ".github" / "scripts" / "release_tags.sh"
GROUP = "revrook-ce-delivery"
DEVELOPMENT_JOB = "Deploy Development (build once, deploy the digest)"
ONE_BUTTON = ("promote-stage.yml", "release.yml")
# The test the gate applies before it dispatches (isOneButton in product-gates.mjs).
GATE_DISPATCH_BLOCK = re.compile(
    r"workflow_dispatch:\s*\n([\s\S]*?)(?:\n\S|\n  [a-z_]+:\s*\n(?!\s{4}))"
)
# Anything that creates a tag, an image tag, a release, a deployment or a ref.
WRITES = (
    "--method POST",
    "--method PATCH",
    "imagetools create",
    "gh release create",
    "dokploy-deploy",
)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


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


def step_source(step: dict[str, Any]) -> str:
    return str(step.get("run", "")) + str(step.get("uses", ""))


def test_the_workflow_set_is_ci_stage_and_release() -> None:
    names = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
    assert names == ["ci.yml", "promote-stage.yml", "release.yml"]
    assert load("ci.yml")["name"] == "CI"
    assert load("promote-stage.yml")["name"] == "Promote - Stage"
    assert load("release.yml")["name"] == "Release"


@pytest.mark.parametrize("name", ONE_BUTTON)
def test_the_gate_can_press_the_button(name: str) -> None:
    triggers = load(name)["on"]
    assert set(triggers) == {"workflow_dispatch"}
    declared = triggers["workflow_dispatch"]["inputs"]
    assert set(declared) == {"dry_run"}
    assert declared["dry_run"]["type"] == "boolean"
    assert declared["dry_run"]["required"] is False
    assert declared["dry_run"]["default"] is False
    block = GATE_DISPATCH_BLOCK.search(text(name))
    assert block is not None
    assert not re.search(r"required:\s*true", block.group(1))


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
def test_no_workflow_deploys_production_or_writes_development(name: str) -> None:
    source = text(name)
    environments = {job.get("environment") for job in load(name)["jobs"].values()}
    assert "production" not in environments
    assert "git/refs/heads/development" not in source
    assert "force=true" not in source


@pytest.mark.parametrize("name", ONE_BUTTON)
def test_the_buttons_never_move_stage_or_main(name: str) -> None:
    # The Actions token may not move a branch to a commit that changes workflow
    # files; the gate script moves stage and main with the operator token.
    source = text(name)
    assert "git/refs/heads/" not in source
    assert "--method PATCH" not in source
    assert "/merges" not in source
    assert not re.search(r"\bgit\s+push\b", source)
    # No guard refuses a run because a branch move would cross workflow files.
    assert "-- .github/workflows" not in source
    assert "GITHUB_TOKEN cannot" not in source


def test_ci_never_touches_stage_or_main() -> None:
    source = text("ci.yml")
    assert "heads/main" not in source
    assert "git/refs/heads/stage" not in source


@pytest.mark.parametrize("name", ONE_BUTTON)
def test_nothing_is_rebuilt(name: str) -> None:
    source = text(name)
    assert "build-push-action" not in source
    assert ":latest" not in source
    assert not re.search(r"docker\s+(buildx\s+)?build\b", source)


@pytest.mark.parametrize("name", ONE_BUTTON)
def test_inputs_reach_scripts_only_through_environment_variables(name: str) -> None:
    for block in run_blocks(name):
        assert "${{" not in block


@pytest.mark.parametrize("name", ONE_BUTTON)
def test_only_development_runs_the_button(name: str) -> None:
    source = text(name)
    assert '[[ "${GITHUB_REF}" == "refs/heads/development" ]]' in source
    # Only the literal true or false is accepted as dry_run.
    assert 'case "${DRY_RUN_INPUT}" in' in source
    assert "DRY_RUN_INPUT: ${{ inputs.dry_run }}" in source


def test_promote_writes_only_after_the_tests_and_never_in_a_dry_run() -> None:
    jobs = load("promote-stage.yml")["jobs"]
    assert set(jobs) == {"plan", "test", "coverage", "promote"}
    promote = jobs["promote"]
    assert promote["if"] == "needs.plan.outputs.dry_run == 'false'"
    assert promote["needs"] == ["plan", "test", "coverage"]
    assert promote["environment"] == "stage"
    for job_id in ("plan", "test", "coverage"):
        for step in jobs[job_id]["steps"]:
            assert not any(write in step_source(step) for write in WRITES), job_id
    first = promote["steps"][1]
    assert first["name"] == "Refuse to write in a dry run and re-check the plan"
    assert '[[ "${DRY_RUN}" == "false" ]]' in first["run"]
    # The suite runs on the commit Development runs, not on the development head.
    for job_id in ("test", "coverage"):
        checkout = jobs[job_id]["steps"][0]
        assert checkout["with"]["ref"] == "${{ needs.plan.outputs.commit }}"
    assert "pytest -q --cov=app" in text("promote-stage.yml")
    assert jobs["test"]["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]


def test_promote_writes_in_the_standard_order() -> None:
    source = text("promote-stage.yml")
    assert "bash .github/scripts/release_tags.sh next" in source
    assert (
        source.index("Create or reuse the annotated release candidate tag")
        < source.index("Tag the immutable image as the candidate version")
        < source.index("uses: ./.github/actions/dokploy-deploy")
        < source.index("Verify Stage health, digest and revision")
        < source.index("Tag the promoted image as stage")
    )


def test_promote_reads_the_stage_branch_only_for_the_summary() -> None:
    plan = load("promote-stage.yml")["jobs"]["plan"]
    steps = {step.get("name"): step for step in plan["steps"]}
    read = steps["Read what Stage runs now"]["run"]
    assert "exit 1" not in read
    assert "merge-base" not in read


def test_promote_deploys_the_registered_stage_application() -> None:
    source = text("promote-stage.yml")
    assert "title: Stage ${{ env.SOURCE_SHA }}" in source
    assert "STAGE_APPLICATION_ID: 7QVBrkTn6rzEcICxV9GTj" in source
    assert "STAGE_HOST: ce-stg-revrook.theriark.dev" in source
    assert "DEV_APPLICATION_ID: zsYpMEYIAGHbJQZuh_1RT" in source
    assert DEVELOPMENT_JOB in source
    action = (ROOT / ".github/actions/dokploy-deploy/action.yml").read_text("utf-8")
    assert "revrook-ce GitHub Actions run ${GITHUB_RUN_ID}" in action


def test_release_publishes_in_the_standard_order() -> None:
    steps = load("release.yml")["jobs"]["release"]["steps"]
    names = [step.get("name") for step in steps]
    assert (
        names.index("Refuse to write in a dry run and re-check stage")
        < names.index("Tag the image with the version")
        < names.index("Create the annotated stable tag")
        < names.index("Create the GitHub Release")
    )


def test_every_release_write_is_skipped_in_a_dry_run() -> None:
    job = load("release.yml")["jobs"]["release"]
    guard = "steps.mode.outputs.dry_run == 'false'"
    writers = [
        step for step in job["steps"] if any(w in step_source(step) for w in WRITES)
    ]
    assert [step["name"] for step in writers] == [
        "Tag the image with the version",
        "Create the annotated stable tag",
        "Create the GitHub Release",
    ]
    for step in writers:
        assert str(step.get("if", "")).startswith(guard), step["name"]
    names = [step.get("name") for step in job["steps"]]
    refuse = names.index("Refuse to write in a dry run and re-check stage")
    assert all(names.index(step["name"]) > refuse for step in writers)
    assert '[[ "${DRY_RUN}" == "false" ]]' in job["steps"][refuse]["run"]


def test_release_reads_what_stage_runs_and_never_deploys() -> None:
    source = text("release.yml")
    assert "dokploy-deploy" not in source
    assert "application.update" not in source
    assert "application.deploy" not in source
    assert "STAGE_APPLICATION_ID: 7QVBrkTn6rzEcICxV9GTj" in source
    assert "+refs/heads/stage:refs/remotes/origin/stage" in source
    assert "bash .github/scripts/release_tags.sh current" in source
    assert "--verify-tag" in source
    assert "--prerelease" not in source
    assert load("release.yml")["jobs"]["release"]["environment"] == "stage"


def test_the_job_names_that_other_workflows_grep_for_exist() -> None:
    names = {key: value["name"] for key, value in load("ci.yml")["jobs"].items()}
    assert names["deploy-development"] == DEVELOPMENT_JOB
    assert DEVELOPMENT_JOB in text("promote-stage.yml")


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


def test_the_tag_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(TAGS_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_the_merge_script_is_gone() -> None:
    # Merging stage into main is the gate's job; no workflow plans or builds it.
    assert not (ROOT / ".github" / "scripts" / "release_merge.sh").exists()


# --- the release tag script on a throwaway repository ---------------------------


def git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    return tmp_path


def commit(repo: Path) -> str:
    git(repo, "commit", "-q", "--allow-empty", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


def tag(repo: Path, name: str, sha: str, digest: str | None = None) -> None:
    message = json.dumps({"imageDigest": digest} if digest else {})
    git(repo, "tag", "-a", name, sha, "-m", message)


def tags(repo: Path, mode: str, sha: str, digest: str) -> dict[str, str]:
    result = subprocess.run(
        ["bash", str(TAGS_SCRIPT), mode, sha, digest],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_the_first_candidate_is_27_0_0_rc_1(repo: Path) -> None:
    sha = commit(repo)
    tag(repo, "v28.0.0-rc.5", sha, DIGEST_B)
    tag(repo, "v1.2.3", sha)
    assert tags(repo, "next", sha, DIGEST_A) == {
        "version": "27.0.0",
        "tag": "v27.0.0-rc.1",
        "exists": "false",
    }


def test_the_same_commit_and_digest_reuse_their_candidate(repo: Path) -> None:
    first = commit(repo)
    tag(repo, "v27.0.0-rc.1", first, DIGEST_A)
    second = commit(repo)
    tag(repo, "v27.0.0-rc.2", second, DIGEST_A)
    assert tags(repo, "next", first, DIGEST_A)["tag"] == "v27.0.0-rc.1"
    assert tags(repo, "next", first, DIGEST_A)["exists"] == "true"
    assert tags(repo, "next", first, DIGEST_B) == {
        "version": "27.0.0",
        "tag": "v27.0.0-rc.3",
        "exists": "false",
    }


def test_after_a_release_the_next_feature_version_opens(repo: Path) -> None:
    released = commit(repo)
    tag(repo, "v27.0.0-rc.1", released, DIGEST_A)
    tag(repo, "v27.0.0", released)
    assert tags(repo, "next", commit(repo), DIGEST_B)["tag"] == "v27.1.0-rc.1"


def test_an_open_fix_line_continues(repo: Path) -> None:
    released = commit(repo)
    tag(repo, "v27.0.0", released)
    tag(repo, "v27.0.1-rc.1", commit(repo), DIGEST_A)
    assert tags(repo, "next", commit(repo), DIGEST_B)["tag"] == "v27.0.1-rc.2"


def test_a_line_below_the_last_release_is_ignored(repo: Path) -> None:
    sha = commit(repo)
    tag(repo, "v27.0.0", sha)
    tag(repo, "v27.0.1-rc.1", sha, DIGEST_A)
    tag(repo, "v27.1.0", commit(repo))
    assert tags(repo, "next", commit(repo), DIGEST_B)["tag"] == "v27.2.0-rc.1"


def test_a_released_commit_is_not_promoted_again(repo: Path) -> None:
    released = commit(repo)
    tag(repo, "v27.0.0-rc.1", released, DIGEST_A)
    tag(repo, "v27.0.0", released)
    # Without the guard this minted v27.1.0-rc.1 for the same code.
    error = tags(repo, "next", released, DIGEST_A)["error"]
    assert "already released as v27.0.0" in error
    assert "error" in tags(repo, "next", released, DIGEST_B)


def test_a_lightweight_candidate_stops_the_run(repo: Path) -> None:
    sha = commit(repo)
    git(repo, "tag", "v27.0.0-rc.1", sha)
    assert "not an annotated tag" in tags(repo, "next", sha, DIGEST_A)["error"]


def test_the_current_candidate_is_the_highest_that_seals_stage(repo: Path) -> None:
    sha = commit(repo)
    tag(repo, "v27.0.0-rc.1", sha, DIGEST_A)
    tag(repo, "v27.0.0-rc.2", sha, DIGEST_B)
    tag(repo, "v27.0.0-rc.3", sha, DIGEST_A)
    assert tags(repo, "current", sha, DIGEST_A) == {
        "version": "27.0.0",
        "tag": "v27.0.0-rc.3",
        "exists": "true",
    }
    assert "error" in tags(repo, "current", commit(repo), DIGEST_A)
