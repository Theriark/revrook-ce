#!/usr/bin/env bash
# Release candidate arithmetic of the release standard, read from the local tags only
# (the caller fetches the tags first). Versions are 27.<minor>.<patch>; no other major
# is ever produced. Tags are annotated; a lightweight tag in a line that is read fails.
#
#   release_tags.sh next <commit> <digest>
#     The candidate Promote - Stage tags. The open line is the highest 27.x.y above the
#     last stable tag that has -rc.N tags and no stable tag. With none open it is 27.0.0
#     before the first release, otherwise the next feature version 27.<minor+1>.0.
#     A candidate of the open line that is already on <commit> and seals <digest> is
#     reused; otherwise the next number of the line is minted.
#   release_tags.sh current <commit> <digest>
#     The candidate Stage runs: the highest -rc.N tag on <commit> that seals <digest>.
#
# Prints version=, tag= and exists= lines (the GITHUB_OUTPUT format).
set -euo pipefail

fail() {
  echo "::error::$*" >&2
  exit 1
}

mode="${1:-}"
commit="${2:-}"
digest="${3:-}"
[[ "${mode}" == "next" || "${mode}" == "current" ]] || fail "usage: release_tags.sh next|current <commit> <digest>"
[[ "${commit}" =~ ^[0-9a-f]{40}$ ]] || fail "commit must be a full 40-character SHA"
[[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "digest must be sha256:<64 hex>"

STABLE='^v27\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
CANDIDATE='^v27\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-rc\.[1-9][0-9]*$'

annotated() {
  [[ "$(git cat-file -t "refs/tags/$1")" == "tag" ]] || fail "$1 is not an annotated tag"
}

# The tag is on the commit and its JSON message seals the digest.
seals() {
  [[ "$(git rev-parse "refs/tags/$1^{commit}")" == "${commit}" ]] || return 1
  git tag -l --format='%(contents)' "$1" |
    jq -e --arg d "${digest}" '.imageDigest == $d' >/dev/null 2>&1
}

mapfile -t candidates < <(git tag -l 'v27.*' | grep -E "${CANDIDATE}" | sort -V || true)
mapfile -t stables < <(git tag -l 'v27.*' | grep -E "${STABLE}" | sort -V || true)

if [[ "${mode}" == "current" ]]; then
  found=""
  for tag in "${candidates[@]}"; do
    if seals "${tag}"; then
      annotated "${tag}"
      found="${tag}"
    fi
  done
  [[ -n "${found}" ]] || fail "no release candidate tag on ${commit} seals ${digest}"
  version="${found#v}"
  echo "version=${version%-rc.*}"
  echo "tag=${found}"
  echo "exists=true"
  exit 0
fi

last_stable=""
if ((${#stables[@]} > 0)); then
  last_stable="${stables[-1]}"
fi
open=""
for tag in "${candidates[@]}"; do
  base="${tag%-rc.*}"
  if [[ -n "${last_stable}" ]]; then
    highest="$(printf '%s\n' "${last_stable}" "${base}" | sort -V | tail -n 1)"
    [[ "${highest}" == "${base}" && "${base}" != "${last_stable}" ]] || continue
  fi
  git rev-parse -q --verify "refs/tags/${base}" >/dev/null || open="${base#v}"
done
if [[ -z "${open}" ]]; then
  if [[ -z "${last_stable}" ]]; then
    open="27.0.0"
  else
    minor="${last_stable#v27.}"
    open="27.$((${minor%%.*} + 1)).0"
  fi
fi

max=0
reuse=""
for tag in "${candidates[@]}"; do
  [[ "${tag}" == "v${open}-rc."* ]] || continue
  annotated "${tag}"
  number="${tag##*-rc.}"
  if ((number > max)); then
    max="${number}"
  fi
  if seals "${tag}"; then
    reuse="${tag}"
  fi
done

echo "version=${open}"
if [[ -n "${reuse}" ]]; then
  echo "tag=${reuse}"
  echo "exists=true"
else
  echo "tag=v${open}-rc.$((max + 1))"
  echo "exists=false"
fi
