# Contributing

Thanks for helping! Overture is a FastAPI backend (`src/overture/`, tested in
`tests/`) with a Svelte frontend (`frontend/`). Its catalog lives in
[OvertureDB](https://github.com/AutoGitr/OvertureDB), checked out beside this
repository as `../OvertureDB`.

Keep settings, the database and the API compatible within a major version,
migrate stored data, and add tests for what you change. The linters and type
checkers enforce the code style.

## Setup

Install the exact versions the project pins: Python in `.python-version`,
[uv](https://docs.astral.sh/uv/) as `required-version` in `pyproject.toml`, and
[Bun](https://bun.sh) as `packageManager` in `frontend/package.json`. CI and the
container build use the same versions. Docker is only needed for container and native builds.

Python is pinned exactly in `requires-python`, `.python-version` and the Docker
image. Update them together, including `uv.lock`; patch releases go through CI
before adoption. Renovate's pinning policy is intentional. A security update
can arrive separately from its tool's Docker update, so check both pins even
when Renovate normally groups them.

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
formats and regenerates contracts. The Git hook runs the quick check of the staged
changes, without tests or builds.

| Task                                           | Command                                                       |
| ---------------------------------------------- | ------------------------------------------------------------- |
| Lint and format Python                         | `uv run ruff check --fix` and `uv run ruff format`            |
| Type-check Python                              | `uv run python -m pyright`                                    |
| Backend tests                                  | `uv run python -m pytest`                                     |
| Frontend checks, in `frontend/`                | `bun run format:fix`, `typecheck`, `lint`, `test:unit`        |
| End-to-end tests, in `frontend/`               | `bun run test:e2e`, and `test:oidc` for sign-in               |
| Import rules and bundle budget, in `frontend/` | `bun run lint:deps`, and `bun run check:bundle` after a build |

### Checking Overture against real media servers

Unit tests replace the media server, TMDB, MDBList, Radarr and Sonarr. To see
how Overture behaves against the real ones, point `scripts/verify.py` at a
synced instance with your servers in `MEDIA_SERVERS`, and at those servers
themselves:

```sh
OVERTURE_API_KEY=key \
PLEX_TOKEN=... JELLYFIN_API_KEY=... EMBY_API_KEY=... \
  uv run python -m scripts.verify http://localhost:5885 \
  --plex https://plex.local:32400 --jellyfin http://jellyfin.local:8096 \
  --emby http://emby.local:8096 --report verify.md
```

Through Overture's API it previews every field and operator, order, list
source and set dimension in each library, checks the collection kind
recommended for each field, previews each managed collection's rule against
the members the server holds, plans the adoption of each unmanaged one, loads
every collection image and reads a sample of contribution issues. Against each
media server directly it compares the libraries, items and collections Overture
lists with the server's own, the values Overture offers with those the server
lists, and Overture's counts with the server's: on Plex as a smart filter,
naming the first title the two disagree on with the values Plex holds for it;
on Jellyfin and Emby with the server's own item filters. It reports every Plex
filter, field, sort and operator, and every Jellyfin and Emby filter, Overture
cannot use. With `TMDB_READ_ACCESS_TOKEN` and `MDBLIST_API_KEY` set, and `--radarr` and
`--sonarr` given with `RADARR_API_KEY` and `SONARR_API_KEY`, it also reads what
those services offer: every TMDB chart, MDBList's lists, list search and title
details (including whether it names a franchise), and Radarr's and Sonarr's
tags, profiles, root folders and import lists against what Overture offers.

It is safe on a real library: Overture is signed in to with API keys (API keys
in the menu), which read and preview but never change, and media servers are
ever sent only GET requests, like every other service. A media server left out is checked through
Overture alone. Pass `--sources sources.json`, a list of source objects as the
API takes them, to include TMDB lists, franchises, people and MDBList lists.
Run it before each release and after changing `src/overture/services/collections/`
or `src/overture/media_servers/`, and turn each problem it reports into a test.

## Generated files

- **API contracts.** After changing endpoints, schemas, WebSocket events or
  setting defaults, run `uv run python -m scripts.contracts`. It regenerates
  `openapi/overture.json` and `frontend/src/generated/`; commit them with your
  change.
- **Media server specs.** `scripts/provider_specs.py` pins the Plex, Jellyfin and
  Emby API specs by version and digest. A changed upstream spec fails until you
  review it and update the pin.
- **OvertureDB contract.** Edit it in `../OvertureDB/schema/`, then copy it here
  with `uv run python -m scripts.catalog_contract ../OvertureDB`.
- **Database migrations.** After changing a model in `src/overture/db/models/`, run
  `uv run alembic revision --autogenerate -m "<summary>"`, review the result and
  add a test in `tests/test_database/test_migrations.py`. Migrations run
  when Overture starts.
- **Brand assets.** See [Brand assets](#brand-assets) for sources, exports and
  the command that also updates OvertureDB.
- **Native archive.** Build it with
  `docker buildx build --platform linux/amd64 --target native-artifact --output type=local,dest=dist .`
  The `native.yml` workflow tests it with `packaging/linux/test.sh`.

## Brand assets

Run `bun run generate:brand --sync-db` from `frontend/` to regenerate both
products and copy every OvertureDB export to the sibling checkout's
`.github/brand/`. Without `--sync-db`, only Overture's checkout is updated.

`frontend/scripts/generate-brand.ts` owns the palettes, exact mark geometry,
optical sizes and layout. The wordmarks and approved tagline are outlined SVGs
in `frontend/design/`; exported mark SVGs in that directory are generated.
The tagline is **Artwork, collections & themes**. Outlined text needs no fonts
on the browser or build machine.

- `*-logo`: the full-size mark, tightly bounded at its natural aspect ratio.
- `*-logo-inline`, `*-logo-stacked`, `*-banner`: measured, centred layouts.
- `*-dark` / `*-light`: explicit palettes for the corresponding backgrounds,
  available as SVG and PNG. Unsuffixed SVGs adapt to the host colour scheme.
- `*-tab.svg`: an optically tuned mark with 1.25px strokes at 16px height;
  PNG versions use square 16, 32 and 48px canvases. Prism keeps its regular
  hexagon proportions, so square canvases have equal space on the left and right.
- `favicon.svg`: Overture's square tab SVG; PNG fallbacks cover 16 and 32px.
- PWA icons use the complete square canvas. Maskable icons keep the mark inside
  the 80%-diameter safe circle; Apple icons use an opaque background and 10%
  inset. These backgrounds fill the canvas, and the mark insets protect it
  from device cropping. Social cards keep intentional space around the logo.

Composite assets use the painted text bounds, preserve aspect ratios, and
centre the icon and text block vertically or horizontally as appropriate.
Spacing between parts is intentional; there is no additional transparent
border around the composite. Do not stretch Prism to fill a square.

The app caches only the brand assets it uses. Full export sets remain available
for repository headers and other uses without bloating the offline cache.

## Documentation

The [documentation site](https://autogitr.github.io/Overture/) is built with
Docusaurus from `docs/`: Overture's pages in `docs/overture/` and OvertureDB's
from the sibling checkout's `docs/`. Preview it with `bun run start` in
`docs/`, and run `bun run ci` there before committing; the build fails on a
broken link in either set of pages. The **Docs** workflow deploys `main` to
GitHub Pages. See [Documentation](https://autogitr.github.io/Overture/overture/developer/documentation)
for how pages are written and how OvertureDB's changes reach the site.

## Dependencies

Add a dependency only when it is clearly needed. Pin the exact version, check
that its license fits, and add it to `licenses/THIRD_PARTY_NOTICES.md`.

## Pull requests

- Branch names start with `feat/`, `fix/`, `refactor/`, `chore/`, `ci/` or
  `docs/`.
- Titles follow [Conventional Commits](https://www.conventionalcommits.org/),
  such as `fix(sync): keep seasons of unconnected shows`; the squash commit uses
  the title.
- Update the pages in `docs/overture/` when behaviour changes, and the
  [README](README.md)'s feature list when a feature is added or removed.
- Describe changes users notice under `## Unreleased` in
  [CHANGELOG.md](CHANGELOG.md), in the same commit.
- Leave out credentials and private media details. Report vulnerabilities as
  described in [SECURITY.md](SECURITY.md).
