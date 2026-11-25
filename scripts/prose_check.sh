#!/usr/bin/env bash
# Run the prose check of CI (the "prose / vale" job) on this machine.
#
# The job runs Vale with the org rules of portolan-sdi/portolan-ops at the
# tag v1. It fails when HEAD has a Vale error that BASE does not have. This
# script does the same on committed files. Commit the change first.
#
# Usage: scripts/prose_check.sh [BASE [HEAD]]
#   BASE defaults to origin/main, HEAD to HEAD.
set -euo pipefail

base=${1:-origin/main}
head=${2:-HEAD}
repo=$(git rev-parse --show-toplevel)
cache="$repo/.cache/prose"
# The ref of the reusable workflow that the CI job calls.
ops_ref=v1

# v1 is a moving tag, so each run clones the workflow and the rules again.
mkdir -p "$cache"
ops="$cache/portolan-ops"
rm -rf "$ops"
git -c advice.detachedHead=false clone -q --depth 1 --branch "$ops_ref" \
  https://github.com/portolan-sdi/portolan-ops.git "$ops"

# The CI job installs the Vale release that VALE_VERSION names in the
# reusable workflow, so this script installs the same release.
vale_version=$(sed -n 's/^ *VALE_VERSION: *\([0-9][0-9.]*\) *$/\1/p' \
  "$ops/.github/workflows/reusable-vale.yml")
if [ -z "$vale_version" ]; then
  echo "error: no VALE_VERSION in the reusable-vale.yml of portolan-ops $ops_ref" >&2
  exit 1
fi
vale="$cache/vale-$vale_version"
if [ ! -x "$vale" ]; then
  release="https://github.com/vale-cli/vale/releases/download/v$vale_version"
  name="vale_${vale_version}_Linux_64-bit.tar.gz"
  sha256=$(curl -fsSL "$release/vale_${vale_version}_checksums.txt" |
    awk -v name="$name" '$2 == name { print $1 }')
  if [ -z "$sha256" ]; then
    echo "error: no checksum for $name in the Vale $vale_version release" >&2
    exit 1
  fi
  archive="$cache/vale.tar.gz"
  curl -fsSL -o "$archive" "$release/$name"
  echo "$sha256  $archive" | sha256sum -c --quiet
  tar -xzf "$archive" -C "$cache" vale
  mv "$cache/vale" "$vale"
  rm "$archive"
fi

(cd "$ops" && PATH="$cache:$PATH" VALE_SYNC_ATTEMPTS=3 \
  bash -c "ln -sf '$vale' '$cache/vale' && ./scripts/vale_sync.sh" >/dev/null)

work=$(mktemp -d)
trap 'git -C "$repo" worktree remove --force "$work/base" 2>/dev/null || true;
      git -C "$repo" worktree remove --force "$work/head" 2>/dev/null || true;
      rm -rf "$work"' EXIT
base_sha=$(git rev-parse "$(git merge-base "$base" "$head")")
head_sha=$(git rev-parse "$head")
for side in base head; do
  sha=${side}_sha
  git -C "$repo" worktree add -q --detach "$work/$side" "${!sha}"
  (cd "$work/$side" && "$vale" --config "$ops/.vale.ini" --glob '*' \
    --minAlertLevel error --output JSON . >"$work/$side.json" || true)
done
git -C "$repo" diff --name-status -z --find-renames "$base_sha" "$head_sha" -- >"$work/renames"
python3 "$ops/scripts/compare_vale.py" "$work/base.json" "$work/head.json" \
  --renames "$work/renames"
