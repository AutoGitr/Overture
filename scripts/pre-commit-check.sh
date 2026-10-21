#!/usr/bin/env bash
set -euo pipefail

# The full check runs what CI runs against the working tree, without rewriting
# anything. --quick is the git pre-commit hook: it checks the staged changes
# without tests or builds. --fix formats and regenerates contracts first.
QUICK=false
FIX=false
case "${1:-}" in
    "") ;;
    --quick) QUICK=true ;;
    --fix) FIX=true ;;
    *) echo "Usage: $0 [--quick|--fix]" >&2; exit 2 ;;
esac

ROOT_DIR="$(git rev-parse --show-toplevel)"
# Every uv command fails instead of silently rewriting a stale uv.lock.
export UV_LOCKED=1

cd "$ROOT_DIR"
BACKEND_CHANGED=false
FRONTEND_CHANGED=false
CONTRACTS_CHANGED=false

if [ "$QUICK" = true ]; then
    CHANGED_FILES="$(git diff --cached --name-only)"
else
    CHANGED_FILES="$(git diff --name-only HEAD; git ls-files --others --exclude-standard)"
fi

if echo "$CHANGED_FILES" | grep -Eq '^(src/|tests/|scripts/[^/]+\.py$|packaging/.+\.py$|pyproject\.toml$|uv\.lock$)'; then BACKEND_CHANGED=true; fi
if echo "$CHANGED_FILES" | grep -q "^frontend/"; then FRONTEND_CHANGED=true; fi
if echo "$CHANGED_FILES" | grep -Eq "^(src/|frontend/|scripts/(contracts|generate_ws_types|generate_settings_defaults)\.py|openapi/overture.json$|pyproject\.toml$)"; then CONTRACTS_CHANGED=true; fi

if [ "$BACKEND_CHANGED" = false ] && [ "$FRONTEND_CHANGED" = false ] && [ "$CONTRACTS_CHANGED" = false ]; then
    BACKEND_CHANGED=true
    FRONTEND_CHANGED=true
    CONTRACTS_CHANGED=true
fi

echo "=== Checking the Lockfile and Release Metadata ==="
if ! uv lock --check; then
    echo "uv.lock does not match pyproject.toml. Run 'uv lock' and commit uv.lock." >&2
    exit 1
fi
uv run python -m scripts.release_metadata

echo "=== Checking Agent Skills ==="
uv run python -m scripts.sync_skills --check

OVERTUREDB_DIR="$ROOT_DIR/../OvertureDB"
if [ -d "$OVERTUREDB_DIR/schema" ]; then
    echo "=== Checking the OvertureDB Contract Copy ==="
    uv run python -m scripts.dataset_contract "$OVERTUREDB_DIR" --check
else
    echo "No OvertureDB checkout at $OVERTUREDB_DIR; skipping the contract drift check."
fi

if [ "$BACKEND_CHANGED" = true ]; then
    echo "=== Running Backend Checks & Tests ==="
    if [ "$FIX" = true ]; then
        uv run ruff check --fix
        uv run ruff format
    else
        uv run ruff check
        uv run ruff format --check
    fi
    uv run python -m pyright
    if [ "$QUICK" = false ]; then
        if [ ! -f "openapi/jellyfin-openapi.json" ] || [ ! -f "openapi/emby-openapi.json" ] || [ ! -f "openapi/plex-openapi.json" ]; then
            echo "=== Preparing Missing Media Server OpenAPI Specifications ==="
            uv run python -m scripts.provider_specs
        fi
        uv run python -m pytest --cov
    fi
fi

if [ "$FRONTEND_CHANGED" = true ] || [ "$CONTRACTS_CHANGED" = true ]; then
    echo "=== Installing Frontend Dependencies ==="
    cd "$ROOT_DIR/frontend"
    if ! bun install --frozen-lockfile; then
        echo "frontend/bun.lock does not match frontend/package.json. Run 'bun install' in frontend and commit bun.lock." >&2
        exit 1
    fi
    cd "$ROOT_DIR"
fi

if [ "$CONTRACTS_CHANGED" = true ]; then
    if [ "$FIX" = true ]; then
        echo "=== Regenerating Generated Contracts ==="
        uv run python -m scripts.contracts
    else
        echo "=== Checking Generated Contracts ==="
        if ! uv run python -m scripts.contracts --check; then
            echo "Generated contracts are stale. Run 'scripts/pre-commit-check.sh --fix' to regenerate them." >&2
            exit 1
        fi
    fi
fi

if [ "$FRONTEND_CHANGED" = true ]; then
    echo "=== Running Frontend Checks & Tests ==="
    cd "$ROOT_DIR/frontend"
    if [ "$FIX" = true ]; then
        bun run format:fix
    fi
    if [ "$QUICK" = true ]; then
        bun run format:check
        bun run typecheck
        bun run lint
    else
        bun run ci
    fi
fi

if [ "$QUICK" = true ]; then
    echo "Quick checks passed. Run scripts/pre-commit-check.sh for the tests and build."
else
    echo "All checks passed successfully."
fi
