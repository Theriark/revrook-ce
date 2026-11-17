"""Contract tests of the delivery workflows (release standard, one button each).

The repository has three workflows: CI, Promote - Stage and Release. Gate 2 dispatches
promote-stage.yml and Gate 3 dispatches release.yml, both on development with no
inputs, so each takes only the optional boolean dry_run. The tests read the workflow
files and run the release tag and merge scripts on throwaway git repositories;
nothing is dispatched and nothing needs a network.
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
MERGE_SCRIPT = ROOT / ".github" / "scripts" / "release_merge.sh"
BUILD_STEP = "Build the merge commit on GitHub, unreferenced"
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


def test_only_release_moves_main_and_only_forward() -> None:
    assert "heads/main" not in text("ci.yml")
    assert "heads/main" not in text("promote-stage.yml")
    source = text("release.yml")
    assert source.count("--method PATCH") == 1
    assert '"repos/${GITHUB_REPOSITORY}/git/refs/heads/main"' in source
    assert "-F force=false" in source
    # A merge commit of main and stage, never a merge into development.
    assert "bash .github/scripts/release_merge.sh" in source
    assert "parents: [$main, $stage]" in MERGE_SCRIPT.read_text(encoding="utf-8")
    assert "[.parents[].sha] == [$main, $stage]" in source
    assert "/merges" not in source


def test_release_moves_main_before_it_publishes_anything() -> None:
    steps = load("release.yml")["jobs"]["release"]["steps"]
    names = [step.get("name") for step in steps]
    assert (
        names.index("Refuse to write in a dry run and re-check stage")
        < names.index("Merge stage into main")
        < names.index("Tag the image with the version")
        < names.index("Create the annotated stable tag")
        < names.index("Create the GitHub Release")
    )


def test_every_release_run_reads_what_could_refuse_the_move_of_main() -> None:
    steps = {s.get("name"): s for s in load("release.yml")["jobs"]["release"]["steps"]}
    plan = steps["Plan the merge of stage into main and read main's rules"]
    # Runs in the dry run too, and fails it on a protection or a refusing rule.
    assert "if" not in plan
    protection = "\"repos/${GITHUB_REPOSITORY}/branches/main\" --jq '.protected'"
    assert protection in plan["run"]
    assert '[[ "${protected}" == "false" ]]' in plan["run"]
    assert '"repos/${GITHUB_REPOSITORY}/rules/branches/main"' in plan["run"]
    assert "grep -vxE 'creation|deletion|non_fast_forward|'" in plan["run"]
    # The merge commit is built on GitHub in the dry run too, and never referenced.
    build = steps[BUILD_STEP]
    assert build["if"] == "steps.merge.outputs.merged == 'false'"
    call = r'--method (\w+) "repos/\$\{GITHUB_REPOSITORY\}/([\w/]+)"'
    posts = re.findall(call, build["run"])
    assert posts == [("POST", "git/trees"), ("POST", "git/commits")]
    assert "git/refs" not in build["run"]


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
        < source.index("Point the stage branch at the deployed commit")
    )
    assert source.count("--method PATCH") == 1
    assert '"repos/${GITHUB_REPOSITORY}/git/refs/heads/stage"' in source


def test_promote_deploys_the_registered_stage_application() -> None:
    source = text("promote-stage.yml")
    assert "title: Stage ${{ env.SOURCE_SHA }}" in source
    assert "STAGE_APPLICATION_ID: 7QVBrkTn6rzEcICxV9GTj" in source
    assert "STAGE_HOST: ce-stg-revrook.theriark.dev" in source
    assert "DEV_APPLICATION_ID: zsYpMEYIAGHbJQZuh_1RT" in source
    assert DEVELOPMENT_JOB in source
    # Stage moves only forward and never across a workflow-file change.
    assert '-- .github/workflows)"' in source
    action = (ROOT / ".github/actions/dokploy-deploy/action.yml").read_text("utf-8")
    assert "revrook-ce GitHub Actions run ${GITHUB_RUN_ID}" in action


def test_every_release_write_is_skipped_in_a_dry_run() -> None:
    job = load("release.yml")["jobs"]["release"]
    guard = "steps.mode.outputs.dry_run == 'false'"
    # The unreferenced merge commit is the only object a dry run creates (see above).
    writers = [
        step
        for step in job["steps"]
        if step.get("name") != BUILD_STEP
        and any(w in step_source(step) for w in WRITES)
    ]
    assert len(writers) == 4
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


@pytest.mark.parametrize("script", (TAGS_SCRIPT, MERGE_SCRIPT), ids=lambda p: p.name)
def test_the_pipeline_scripts_are_valid_bash(script: Path) -> None:
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


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


# --- the merge of stage into main on a throwaway repository ---------------------


def write(repo: Path, path: str, content: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def snapshot(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def plan_merge(repo: Path, main: str, stage: str) -> dict[str, str]:
    out = repo / ".merge"
    out.mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(MERGE_SCRIPT), main, stage, "Release v27.0.0", str(out)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def payload(repo: Path, name: str) -> dict[str, Any]:
    content = (repo / ".merge" / name).read_text(encoding="utf-8")
    return json.loads(content)  # type: ignore[no-any-return]


@pytest.fixture
def diverged(repo: Path) -> tuple[Path, str, str]:
    """main has a commit of its own (a workflow registration) that stage lacks."""
    write(repo, "README.md", "root\n")
    root = snapshot(repo, "root")
    write(repo, ".github/workflows/ci.yml", "registered on main\n")
    main = snapshot(repo, "register ci.yml on main")
    git(repo, "checkout", "-q", "--detach", root)
    write(repo, "app.py", "print('stage')\n")
    write(repo, ".github/workflows/ci.yml", "changed on development\n")
    write(repo, ".github/workflows/release.yml", "new on development\n")
    stage = snapshot(repo, "the product")
    return repo, main, stage


def test_the_merge_commit_has_the_parents_main_then_stage(
    diverged: tuple[Path, str, str],
) -> None:
    repo, main, stage = diverged
    planned = plan_merge(repo, main, stage)
    assert planned["merged"] == "false"
    assert planned["workflow_commits"] == "1"
    commit_payload = payload(repo, "commit.json")
    assert commit_payload["parents"] == [main, stage]
    assert commit_payload["tree"] == planned["tree"]
    # A real merge commit: main is not fast-forwarded to stage, and both histories stay.
    tree = planned["tree"]
    merge = git(repo, "commit-tree", tree, "-p", main, "-p", stage, "-m", "merge")
    parents = git(repo, "rev-list", "--parents", "-n", "1", merge).split()[1:]
    assert parents == [main, stage]
    assert merge != stage
    # Once main holds the merge, stage is in main and a re-run merges nothing.
    assert plan_merge(repo, merge, stage) == {"merged": "true"}


def test_the_planned_tree_keeps_mains_workflows_and_takes_stages_files(
    diverged: tuple[Path, str, str],
) -> None:
    repo, main, stage = diverged
    tree = plan_merge(repo, main, stage)["tree"]
    workflows = git(repo, "rev-parse", f"{main}:.github/workflows")
    assert git(repo, "rev-parse", f"{tree}:.github/workflows") == workflows
    app = git(repo, "rev-parse", f"{stage}:app.py")
    assert git(repo, "rev-parse", f"{tree}:app.py") == app
    assert git(repo, "diff", "--name-only", main, tree, "--", ".github/workflows") == ""
    # GitHub builds the same tree: stage's tree with main's workflow subtree.
    entry = {"path": ".github/workflows", "mode": "040000", "type": "tree"}
    assert payload(repo, "tree.json") == {
        "base_tree": git(repo, "rev-parse", f"{stage}^{{tree}}"),
        "tree": [{**entry, "sha": workflows}],
    }


def test_a_main_without_workflows_drops_stages_workflows(repo: Path) -> None:
    write(repo, "README.md", "root\n")
    main = snapshot(repo, "root")
    write(repo, ".github/workflows/ci.yml", "on development\n")
    stage = snapshot(repo, "the product")
    tree = plan_merge(repo, main, stage)["tree"]
    assert git(repo, "ls-tree", "-r", "--name-only", tree) == "README.md"
    assert payload(repo, "tree.json")["tree"][0]["sha"] is None
