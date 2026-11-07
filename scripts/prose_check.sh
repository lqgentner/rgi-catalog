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
# The Vale release and the rules ref of the CI job.
vale_version=3.19.0
vale_sha256=c8f9d6c8055442bc7e9c121b2498e6f0e3fb670f4665e6ee577f1897f7665cf6
ops_ref=v1

mkdir -p "$cache"
vale="$cache/vale-$vale_version"
if [ ! -x "$vale" ]; then
  archive="$cache/vale.tar.gz"
  curl -fsSL -o "$archive" \
    "https://github.com/vale-cli/vale/releases/download/v$vale_version/vale_${vale_version}_Linux_64-bit.tar.gz"
  echo "$vale_sha256  $archive" | sha256sum -c --quiet
  tar -xzf "$archive" -C "$cache" vale
  mv "$cache/vale" "$vale"
  rm "$archive"
fi

# v1 is a moving tag, so each run clones the rules again.
ops="$cache/portolan-ops"
rm -rf "$ops"
git -c advice.detachedHead=false clone -q --depth 1 --branch "$ops_ref" \
  https://github.com/portolan-sdi/portolan-ops.git "$ops"
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
