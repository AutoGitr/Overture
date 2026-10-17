#!/usr/bin/env bash
set -euo pipefail

# --quick is the git pre-commit hook: it checks the staged changes without
# rewriting files, running tests or building. Run the full check before pushing.
QUICK=false
case "${1:-}" in
    "") ;;
    --quick) QUICK=true ;;
    *) echo "Usage: $0 [--quick]" >&2; exit 2 ;;
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
    CHANGED_FILES="$(git diff --name-only HEAD)"
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
    if [ "$QUICK" = true ]; then
        uv run ruff check
        uv run ruff format --check
    else
        uv run ruff check --fix
        uv run ruff format
    fi
    uv run python -m pyright
    if [ "$QUICK" = false ]; then
        if [ ! -f "openapi/jellyfin-openapi.json" ] || [ ! -f "openapi/emby-openapi.json" ] || [ ! -f "openapi/plex-openapi.json" ]; then
            echo "=== Preparing Missing Media Server OpenAPI Specifications ==="
            uv run python -m scripts.provider_specs
        fi
        uv run python -m pytest
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

if [ "$CONTRACTS_CHANGED" = true ] && [ "$QUICK" = true ]; then
    echo "=== Checking Generated Contracts ==="
    if ! uv run python -m scripts.contracts --check; then
        echo "Generated contracts are stale. Run 'uv run python -m scripts.contracts' and stage the result." >&2
        exit 1
    fi
elif [ "$CONTRACTS_CHANGED" = true ]; then
    echo "=== Regenerating Generated Contracts ==="
    uv run python -m scripts.contracts

    changed_contracts="$(
        {
            git diff --name-only -- openapi/overture.json frontend/src/generated/rest frontend/src/generated/ws.ts frontend/src/generated/settings.ts
            git ls-files --others --exclude-standard -- openapi/overture.json frontend/src/generated/rest frontend/src/generated/ws.ts frontend/src/generated/settings.ts
        } | sed '/^$/d' | sort -u
    )"
    if [ -n "$changed_contracts" ]; then
        echo "Generated contracts changed. Stage these files and rerun pre-commit-check.sh:"
        echo "$changed_contracts"
        exit 1
    fi
fi

if [ "$FRONTEND_CHANGED" = true ]; then
    echo "=== Running Frontend Checks & Tests ==="
    cd "$ROOT_DIR/frontend"
    if [ "$QUICK" = true ]; then
        bun run format:check
    else
        bun run format:fix
    fi
    bun run typecheck
    bun run lint
    if [ "$QUICK" = false ]; then
        bun run build
        bun run test:unit
    fi
fi

if [ "$QUICK" = true ]; then
    echo "Quick checks passed. Run scripts/pre-commit-check.sh for the tests and build."
else
    echo "All checks passed successfully."
fi
