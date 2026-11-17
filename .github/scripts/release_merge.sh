#!/usr/bin/env bash
# The merge of stage into main that Release makes (release standard): a real merge
# commit with the parents [main, stage], in that order, never a fast-forward of main to
# stage (main has commits of its own). Its tree is stage's tree except
# .github/workflows, which stays main's own: GITHUB_TOKEN cannot change workflow files,
# and the workflow-only route registers them on main.
#
#   release_merge.sh <main> <stage> <message> <out-dir>
#
# Prints merged=true when stage is already in main (nothing to do). Otherwise it builds
# the planned tree in a private index, checks that it changes no workflow file of main,
# writes the two GitHub payloads <out-dir>/tree.json (Git trees API: stage's tree with
# main's .github/workflows) and <out-dir>/commit.json (Git commits API: the planned
# tree, parents [main, stage]) and prints merged=false, tree= and workflow_commits=
# (how many commits of stage that main lacks touch .github/workflows).
# Reads the local repository only; it creates no object on GitHub and moves no ref.
set -euo pipefail

fail() {
  echo "::error::$*" >&2
  exit 1
}

main="${1:-}"
stage="${2:-}"
message="${3:-}"
out="${4:-}"
usage="usage: release_merge.sh <main sha> <stage sha> <message> <out-dir>"
[[ "${main}" =~ ^[0-9a-f]{40}$ && "${stage}" =~ ^[0-9a-f]{40}$ ]] || fail "${usage}"
[[ -n "${message}" && -d "${out}" ]] || fail "${usage}"

if git merge-base --is-ancestor "${stage}" "${main}"; then
  echo "merged=true"
  exit 0
fi

workflows="$(git rev-parse -q --verify "${main}:.github/workflows" || true)"
scratch="$(mktemp -d)"
trap 'rm -rf "${scratch}"' EXIT
index="${scratch}/merge.index"
GIT_INDEX_FILE="${index}" git read-tree "${stage}"
GIT_INDEX_FILE="${index}" git rm -r -q -f --cached --ignore-unmatch .github/workflows
if [[ -n "${workflows}" ]]; then
  GIT_INDEX_FILE="${index}" git read-tree --prefix=.github/workflows/ "${workflows}"
fi
tree="$(GIT_INDEX_FILE="${index}" git write-tree)"
[[ -z "$(git diff --name-only "${main}" "${tree}" -- .github/workflows)" ]] || fail "the planned main tree changes workflow files"

# The same tree, built on GitHub from objects it already has.
jq -n --arg base "$(git rev-parse "${stage}^{tree}")" --arg wf "${workflows}" '
    {base_tree: $base, tree: [{path: ".github/workflows", mode: "040000", type: "tree",
      sha: (if $wf == "" then null else $wf end)}]}' > "${out}/tree.json"
jq -n --arg tree "${tree}" --arg main "${main}" --arg stage "${stage}" --arg m "${message}" '
    {message: $m, tree: $tree, parents: [$main, $stage]}' > "${out}/commit.json"

echo "merged=false"
echo "tree=${tree}"
echo "workflow_commits=$(git rev-list --count "${main}..${stage}" -- .github/workflows)"
