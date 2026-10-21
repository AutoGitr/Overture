# Contributing

Thanks for helping! Overture is a FastAPI backend (`src/overture/`, tested in
`tests/`) with a Svelte frontend (`frontend/`). Its catalog lives in
[OvertureDB](https://github.com/AutoGitr/OvertureDB), checked out beside this
repository as `../OvertureDB`.

Keep settings, the database and the API compatible within a major version,
migrate stored data, and add tests for what you change. The linters and type
checkers enforce the code style.

## Setup

Install the exact versions the project pins: Python and
[uv](https://docs.astral.sh/uv/) in `pyproject.toml`, [Bun](https://bun.sh) in
`frontend/package.json`. Docker is only needed for container and native builds.

```sh
uv sync --locked --group dev
uv run python -m scripts.provider_specs   # pinned media server API specs for tests
cd frontend && bun install --frozen-lockfile
git config core.hooksPath .githooks       # quick checks on every commit
```

Run the backend with a local settings file. After `setup`, add an absolute
`OVERTURE_CONFIG_DIR` line to it:

```sh
uv run overture setup --config-file ./config/overture.env
uv run overture serve --config-file ./config/overture.env
cd frontend && bun run dev                # Vite with hot reload on :5173
```

`bun run build` writes the web interface into `src/overture/frontend/`, where
the backend serves it from.

## Checks

Before committing, run:

```sh
bash scripts/pre-commit-check.sh
```

It runs the checks CI runs on what changed: lockfiles, generated files,
formatting, lint, types, tests with their coverage thresholds, and builds.
`bash scripts/pre-commit-check.sh --fix` formats and
regenerates contracts first. The Git hook runs the quick check of the staged
changes, without tests or builds.

| Task | Command |
| --- | --- |
| Lint and format Python | `uv run ruff check --fix` and `uv run ruff format` |
| Type-check Python | `uv run python -m pyright` |
| Backend tests | `uv run python -m pytest` |
| Frontend checks, in `frontend/` | `bun run format:fix`, `typecheck`, `lint`, `test:unit` |
| End-to-end tests, in `frontend/` | `bun run test:e2e`, and `test:oidc` for sign-in |

## Generated files

- **API contracts.** After changing endpoints, schemas, WebSocket events or
  setting defaults, run `uv run python -m scripts.contracts`. It regenerates
  `openapi/overture.json` and `frontend/src/generated/`; commit them with your
  change.
- **Media server specs.** `scripts/provider_specs.py` pins the Plex, Jellyfin and
  Emby API specs by version and digest. A changed upstream spec fails until you
  review it and update the pin.
- **OvertureDB contract.** Edit it in `../OvertureDB/schema/`, then copy it here
  with `uv run python -m scripts.dataset_contract ../OvertureDB`.
- **Database migrations.** After changing a model in `src/overture/db/models/`, run
  `uv run alembic revision --autogenerate -m "<summary>"`, review the result and
  add a test in `tests/test_database/test_migrations.py`. Migrations run
  when Overture starts.
- **Brand assets.** Sources are in `frontend/design/`. Run
  `bun run generate:brand` in `frontend/`, commit the exports, and copy the
  OvertureDB stacked logos to OvertureDB's `.github/brand/`.
- **Native archive.** Build it with
  `docker buildx build --platform linux/amd64 --target native-artifact --output type=local,dest=dist .`
  The `native.yml` workflow tests it with `packaging/linux/test.sh`.

## Dependencies

Add a dependency only when it is clearly needed. Pin the exact version, check
that its license fits, and add it to `licenses/THIRD_PARTY_NOTICES.md`.

## Pull requests

- Branch names start with `feat/`, `fix/`, `refactor/`, `chore/`, `ci/` or
  `docs/`.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/),
  such as `fix(sync): keep seasons of unconnected shows`; the squash commit uses
  the title.
- Update the [README](README.md) when behaviour changes.
- Describe changes users notice under `## [Unreleased]` in
  [CHANGELOG.md](CHANGELOG.md), in the same commit.
- Leave out credentials and private media details. Report vulnerabilities as
  described in [SECURITY.md](SECURITY.md).

## Releases

Maintainers only. Pushing a `vX.Y.Z` tag triggers the **Release** workflow,
which qualifies the tag and publishes after the `release` environment approves
it. Overture follows [Semantic Versioning](https://semver.org/):
- **PATCH** (`1.0.x`): Backward-compatible fixes (`fix:`, `perf:`, `deps:`).
- **MINOR** (`1.x.0`): Backward-compatible new features or settings (`feat:`).
- **MAJOR** (`x.0.0`): Breaking database, API, or environment changes (`feat!:`, `BREAKING CHANGE:`).

Release `main` with one command:

```sh
bash scripts/release.sh X.Y.Z
```

It checks that `main` matches `origin` and that every check on it passed, sets
the version across `pyproject.toml`, `uv.lock`, `frontend/package.json` and
`openapi/overture.json`, moves the `[Unreleased]` entries of
[CHANGELOG.md](CHANGELOG.md) under `## [X.Y.Z] - <date>`, runs the full
check, then pushes a signed release commit and `vX.Y.Z` tag together.

The workflow runs CI, native Linux qualification and release validation, builds
the native archive, pushes the `amd64` and `arm64` image by digest, scans and
signs it, attaches SBOMs and provenance, and smoke-tests both platforms. Only
then does it add the container tags (`X.Y.Z`, `X.Y`, `X` and `latest`) and
create the GitHub release, whose notes are the version's changelog section
followed by the image digest.

If the run fails before that, fix the workflow on `main` and run **Release**
from `main` with the tag as input; it rebuilds the tagged source. Never move or
reuse a published version: publish a patch release to fix a bad one.

GHCR signatures go to the `ghcr.io/autogitr/overture-signatures` package. The
workflow verifies the GHCR image and its signature without credentials, as a
user would, so it stops when either package is private. A package created by
the workflow can start private: make it public once and rerun the failed job.

Never delete untagged versions of the `overture` package: a release is an index
with one image and one attestation manifest per platform, and only the index is
tagged.

Repository settings: protect `main` and `v*` tags, require the CI, CodeQL and
Trivy checks, and keep Actions permissions read-only by default. Repository
labels are defined in `.github/labels.json`. Preview changes with
`uv run --locked python -m scripts.sync_labels`; use `--apply` to reconcile them
or `--check` to detect drift.
