#!/usr/bin/env bash
set -euo pipefail

# Releases X.Y.Z from main as it is on origin: sets the version, moves the
# unreleased changelog entries under it, runs the full check, then pushes a
# signed commit and tag together. The tag starts the Release workflow.
if [ $# -ne 1 ]; then
    echo "Usage: $0 X.Y.Z" >&2
    exit 2
fi
VERSION="${1#v}"
TAG="v$VERSION"

cd "$(git rev-parse --show-toplevel)"

if [ "$(git branch --show-current)" != main ]; then
    echo "Release from main." >&2
    exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
    echo "Commit or stash your changes first." >&2
    exit 1
fi
git fetch --quiet origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
    echo "main differs from origin/main; pull or push first." >&2
    exit 1
fi
# Release tags are protected and cannot be moved or deleted once pushed.
if git rev-parse --quiet --verify "refs/tags/$TAG" >/dev/null \
    || git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null; then
    echo "$TAG already exists." >&2
    exit 1
fi
# A version is lost if the Release workflow fails on what the tag builds, so
# only tag on top of a commit whose checks, CI among them, all passed.
read -r ci_passed unfinished < <(
    gh api "repos/{owner}/{repo}/commits/$(git rev-parse HEAD)/check-runs?per_page=100" \
        --jq '"\([.check_runs[] | select(.name == "ci-result" and .conclusion == "success")] | length) \([.check_runs[] | select(.status != "completed" or (.conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral"))] | length)"'
)
if [ "$ci_passed" -eq 0 ] || [ "$unfinished" -ne 0 ]; then
    echo "The checks on main have not all passed yet; wait for them or fix main." >&2
    exit 1
fi

# The tree was clean, so a failed or interrupted check leaves nothing to keep.
trap 'git checkout -- .' EXIT
uv run --locked python -m scripts.release_metadata --prepare "$VERSION"
bash scripts/pre-commit-check.sh
trap - EXIT

git commit --all --gpg-sign --message "chore: release $TAG"
git tag --sign "$TAG" --message "Release $TAG"
git push --atomic origin main "$TAG"
echo "Pushed $TAG. Approve the release environment in the Release workflow."
