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
SEMVER='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
if [[ ! "$VERSION" =~ $SEMVER ]]; then
    echo "$VERSION is not a stable semantic version (X.Y.Z)." >&2
    exit 2
fi

cd "$(git rev-parse --show-toplevel)"

if ! gh auth status >/dev/null 2>&1; then
    echo "Sign in to GitHub with 'gh auth login' first." >&2
    exit 1
fi
if [ -z "$(git config --get user.signingkey)" ]; then
    echo "Set user.signingkey: main and release tags must be signed." >&2
    exit 1
fi
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

# The next version follows the newest one in use, whether as the project
# version or as a release tag, so a typo can neither go back nor skip ahead.
current="$(uv run --locked python -m scripts.release_metadata)"
newest="$(
    {
        echo "$current"
        git ls-remote --tags --refs origin 'v*' | sed 's#.*refs/tags/v##' | grep -E "$SEMVER" || true
    } | sort -V | tail -n 1
)"
IFS=. read -r major minor patch <<< "$newest"
allowed="$major.$minor.$((patch + 1)) $major.$((minor + 1)).0 $((major + 1)).0.0"
if [[ " $allowed " != *" $VERSION "* ]]; then
    echo "$VERSION does not follow $newest; release one of: $allowed." >&2
    exit 1
fi
if git rev-parse --quiet --verify "refs/tags/$TAG" >/dev/null; then
    echo "A local $TAG tag is left from an earlier attempt; delete it with 'git tag -d $TAG'." >&2
    exit 1
fi

# Release tags must be impossible to move or delete once pushed.
tag_rules=""
for id in $(gh api "repos/{owner}/{repo}/rulesets" \
    --jq '.[] | select(.target == "tag" and .enforcement == "active") | .id'); do
    tag_rules+="$(gh api "repos/{owner}/{repo}/rulesets/$id" \
        --jq 'select(.conditions.ref_name.include | index("refs/tags/v*")) | .rules[].type')"$'\n'
done
if ! grep -qx deletion <<< "$tag_rules" || ! grep -qx update <<< "$tag_rules"; then
    echo "No active ruleset stops v* tags from being moved or deleted; enable it first." >&2
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
