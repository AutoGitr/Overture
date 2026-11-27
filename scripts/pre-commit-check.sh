#!/usr/bin/env bash
set -euo pipefail

# The full check runs what CI runs against the working tree, without rewriting
# anything. --quick is the git pre-commit hook: it checks the staged changes
# without tests or builds. --fix brings the lockfiles in line with their
# manifests (never upgrading anything), formats and regenerates contracts first.
QUICK=false
FIX=false
case "${1:-}" in
    "") ;;
    --quick) QUICK=true ;;
    --fix) FIX=true ;;
    *) echo "Usage: $0 [--quick|--fix]" >&2; exit 2 ;;
esac

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

if [ "$FIX" = true ]; then
    echo "=== Updating the Lockfiles ==="
    uv lock
    (cd frontend && bun install)
fi
# Every uv command fails instead of silently rewriting a stale uv.lock.
export UV_LOCKED=1

BACKEND_CHANGED=false
FRONTEND_CHANGED=false
CONTRACTS_CHANGED=false
DUPLICATION_CHANGED=false

if [ "$QUICK" = true ]; then
    CHANGED_FILES="$(git diff --cached --name-only)"
else
    CHANGED_FILES="$(git diff --name-only HEAD; git ls-files --others --exclude-standard)"
fi

if echo "$CHANGED_FILES" | grep -Eq '^(src/|tests/|scripts/[^/]+\.py$|packaging/.+\.py$|pyproject\.toml$|uv\.lock$)'; then BACKEND_CHANGED=true; fi
if echo "$CHANGED_FILES" | grep -q "^frontend/"; then FRONTEND_CHANGED=true; fi
if echo "$CHANGED_FILES" | grep -Eq '^(src/|frontend/src/|scripts/|docs/overture/|\.jscpd\.json$)'; then DUPLICATION_CHANGED=true; fi
if echo "$CHANGED_FILES" | grep -Eq "^(src/|frontend/|scripts/(contracts|generate_ws_types|generate_settings_defaults)\.py|openapi/overture.json$|pyproject\.toml$)"; then CONTRACTS_CHANGED=true; fi

if [ "$BACKEND_CHANGED" = false ] && [ "$FRONTEND_CHANGED" = false ] && [ "$CONTRACTS_CHANGED" = false ]; then
    BACKEND_CHANGED=true
    FRONTEND_CHANGED=true
    CONTRACTS_CHANGED=true
    DUPLICATION_CHANGED=true
fi

echo "=== Checking the Lockfile and Release Metadata ==="
if ! uv lock --check; then
    echo "uv.lock does not match pyproject.toml. Run 'uv lock' and commit uv.lock." >&2
    exit 1
fi
if [ "$FIX" = true ]; then
    uv run python -m scripts.release_metadata --format-changelog
else
    uv run python -m scripts.release_metadata
fi

echo "=== Checking Agent Skills ==="
if [ "$FIX" = true ]; then
    uv run python -m scripts.sync_skills
else
    uv run python -m scripts.sync_skills --check
fi

echo "=== Auditing GitHub Workflows ==="
uv run zizmor --offline --quiet .github/workflows

OVERTUREDB_DIR="$ROOT_DIR/../OvertureDB"
if [ -d "$OVERTUREDB_DIR/schema" ]; then
    echo "=== Checking the OvertureDB Contract Copy ==="
    uv run python -m scripts.preset_contract "$OVERTUREDB_DIR" --check
    uv run python -m scripts.catalog_contract "$OVERTUREDB_DIR" --check
else
    echo "No OvertureDB checkout at $OVERTUREDB_DIR; skipping the contract drift check."
fi

if [ "$BACKEND_CHANGED" = true ]; then
    echo "=== Running Backend Static Checks ==="
    if [ "$FIX" = true ]; then
        # Formatting first, so the check sees the lines the formatter wraps.
        uv run ruff format
        uv run ruff check --fix
    else
        uv run ruff format --check
        uv run ruff check
    fi
    uv run python -m pyright
fi

if [ "$FRONTEND_CHANGED" = true ] || [ "$CONTRACTS_CHANGED" = true ] || [ "$DUPLICATION_CHANGED" = true ]; then
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
    echo "=== Running Frontend Static Checks ==="
    cd "$ROOT_DIR/frontend"
    if [ "$FIX" = true ]; then
        bun run format:fix
    fi
    bun run format:check
    bun run lint:deps
    bun run lint
    bun run lint:unused
    bun run typecheck
    cd "$ROOT_DIR"
fi

if [ "$DUPLICATION_CHANGED" = true ]; then
    echo "=== Checking for Duplicated Code ==="
    (cd "$ROOT_DIR/frontend" && bun run lint:duplication)
fi

if [ "$QUICK" = true ]; then
    echo "Quick checks passed. Run scripts/pre-commit-check.sh for the tests and build."
    exit 0
fi

if [ "$BACKEND_CHANGED" = true ]; then
    echo "=== Running Backend Tests ==="
    if [ ! -f "openapi/jellyfin-openapi.json" ] || [ ! -f "openapi/emby-openapi.json" ] || [ ! -f "openapi/plex-openapi.json" ]; then
        echo "=== Preparing Missing Media Server OpenAPI Specifications ==="
        uv run python -m scripts.provider_specs
    fi
    uv run python -m pytest -n auto --dist=worksteal -m "not serial" --cov --cov-report= --cov-fail-under=0
    uv run python -m pytest -m serial --cov --cov-append
fi

if [ "$FRONTEND_CHANGED" = true ]; then
    echo "=== Running Frontend Tests & Build ==="
    cd "$ROOT_DIR/frontend"
    bun run test:coverage
    bun run build
    bun run check:bundle
    cd "$ROOT_DIR"
fi

echo "All checks passed successfully."
