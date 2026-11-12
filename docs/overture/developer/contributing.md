---
sidebar_position: 1
title: Contributing
description: Setting up a development environment and running the checks.
---

# Contributing

Thanks for helping! Overture is a FastAPI backend (`src/overture/`, tested in
`tests/`) with a Svelte frontend (`frontend/`). Its catalog lives in
[OvertureDB](https://github.com/AutoGitr/OvertureDB), checked out beside this
repository as `../OvertureDB`.

Keep settings, the database and the API compatible within a major version,
migrate stored data, and add tests for what you change. The linters and type
checkers enforce the code style.

Share artwork and theme selections through
[OvertureDB](/overturedb/contributing) instead if that is what you came for.

## Setup

Install the exact versions the project pins: Python in `.python-version`,
[uv](https://docs.astral.sh/uv/) as `required-version` in `pyproject.toml`,
and [Bun](https://bun.sh) as `packageManager` in `frontend/package.json`. CI
and the container build use the same versions. Docker is only needed for
container and native builds.

Python is pinned exactly in `requires-python`, `.python-version` and the
Docker image. Update them together, including `uv.lock`; patch releases go
through CI before adoption. Renovate's pinning policy is intentional. A
security update can arrive separately from its tool's Docker update, so check
both pins even when Renovate normally groups them.

```sh
uv sync --locked --group dev
uv run python -m scripts.provider_specs   # pinned media server API specs for tests
(cd frontend && bun install --frozen-lockfile)
uv run python -m scripts.sync_skills      # agent skills the installed packages ship
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
`bash scripts/pre-commit-check.sh --fix` first updates `uv.lock` and
`frontend/bun.lock` to match their manifests (it never upgrades anything),
formats and regenerates contracts. The Git hook runs the quick check of the
staged changes, without tests or builds.

| Task                                           | Command                                                       |
| ---------------------------------------------- | ------------------------------------------------------------- |
| Lint and format Python                         | `uv run ruff check --fix` and `uv run ruff format`            |
| Type-check Python                              | `uv run python -m pyright`                                    |
| Backend tests                                  | `uv run python -m pytest`                                     |
| Frontend checks, in `frontend/`                | `bun run format:fix`, `typecheck`, `lint`, `test:unit`        |
| End-to-end tests, in `frontend/`               | `bun run test:e2e`, and `test:oidc` for sign-in               |
| Import rules and bundle budget, in `frontend/` | `bun run lint:deps`, and `bun run check:bundle` after a build |
| Documentation, in `docs/`                      | `bun run ci`; see [Documentation](documentation.md)           |

### Checking Overture against real media servers

Unit tests replace the media server, TMDB, MDBList, Radarr and Sonarr. To see
how Overture behaves against the real ones, point `scripts/verify.py` at
synced instances, one per media server, and at those servers themselves:

```sh
OVERTURE_API_KEY=plex-key,jellyfin-key,emby-key \
PLEX_TOKEN=... JELLYFIN_API_KEY=... EMBY_API_KEY=... \
  uv run python -m scripts.verify \
  http://localhost:5885 http://localhost:5886 http://localhost:5887 \
  --plex https://plex.local:32400 --jellyfin http://jellyfin.local:8096 \
  --emby http://emby.local:8096 --report verify.md
```

Through Overture's API it previews every field and operator, order, list
source and set dimension in each library, checks the collection kind
recommended for each field, previews each managed collection's rule against
the members the server holds, plans the adoption of each unmanaged one, loads
every collection image and reads a sample of contribution issues. Against each
media server directly it compares the libraries, items and collections
Overture lists with the server's own, the values Overture offers with those
the server lists, and Overture's counts with the server's: on Plex as a smart
filter, naming the first title the two disagree on with the values Plex holds
for it; on Jellyfin and Emby with the server's own item filters. It reports
every Plex filter, field, sort and operator, and every Jellyfin and Emby
filter, Overture cannot use. With `TMDB_API_KEY` and `MDBLIST_API_KEY` set,
and `--radarr` and `--sonarr` given with `RADARR_API_KEY` and
`SONARR_API_KEY`, it also reads what those services offer: every TMDB chart,
MDBList's lists, list search and title details (including whether it names a
franchise), and Radarr's and Sonarr's tags, profiles, root folders and import
lists against what Overture offers.

It is safe on a real library: Overture is signed in to with API keys (API keys
in the menu), which read and preview but never change, and media servers are
only ever sent GET requests, like every other service. A media server left out
is checked through Overture alone. Pass `--sources sources.json`, a list of
source objects as the API takes them, to include TMDB lists, franchises,
people and MDBList lists. With `--write` it also makes, changes and deletes
temporary "zz Overture verify" collections with Overture's own media server
clients, to show how each server takes them. Run it before each release and
after changing `src/overture/services/collections/` or
`src/overture/media_servers/`, and turn each problem it reports into a test.

## Dependencies

Add a dependency only when it is clearly needed. Pin the exact version, check
that its license fits, and add it to `licenses/THIRD_PARTY_NOTICES.md`.

## Pull requests

- Branch names start with `feat/`, `fix/`, `refactor/`, `chore/`, `ci/` or
  `docs/`.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/),
  such as `fix(sync): keep seasons of unconnected shows`; the squash commit
  uses the title.
- Update these docs when behaviour changes, and the README's feature list
  when a feature is added or removed, written for the person running Overture:
  what it does and how to use it, never how it was built.
- Describe changes users notice under `## [Unreleased]` in
  [CHANGELOG.md](https://github.com/AutoGitr/Overture/blob/main/.github/CHANGELOG.md),
  in the same commit. It follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
  and becomes the release notes.
- Leave out credentials and private media details. Report vulnerabilities as
  described under [Support](../support.md#security).

Repository labels are defined in `.github/labels.json`. Preview changes with
`uv run --locked python -m scripts.sync_labels`; use `--apply` to reconcile
them or `--check` to detect drift.
