# Maintaining Overture

The repository owner's runbook: cutting releases, the repository's settings,
deploying the documentation site and regenerating the brand assets. Contributors
need none of it; their guide is [Contributing](https://autogitr.github.io/Overture/overture/developer/contributing).

## Releases

Pushing a `vX.Y.Z` tag triggers the **Release** workflow,
which qualifies the tag and publishes after the `release` environment approves
it. Overture follows [Semantic Versioning](https://semver.org/):

- **PATCH** (`1.0.x`): Backward-compatible fixes (`fix:`, `perf:`, `deps:`).
- **MINOR** (`1.x.0`): Backward-compatible new features or settings (`feat:`).
- **MAJOR** (`x.0.0`): Breaking database, API, or environment changes
  (`feat!:`, `BREAKING CHANGE:`).

### Cutting a release

Release `main` with one command:

```sh
bash scripts/release.sh X.Y.Z
```

It checks that `main` matches `origin` and that every workflow its push
started passed, that `X.Y.Z` is the next patch, minor or major version after
the newest one in use, and that a ruleset still protects `v*` tags. It then
starts the **Release check** workflow on that commit: the native Linux
qualification and the capacity and soak validation, which CI leaves to
releases. While that runs, it sets the version across `pyproject.toml`,
`uv.lock`, `frontend/package.json` and `openapi/overture.json`, moves the
`Unreleased` entries of the changelog under `## X.Y.Z - <date>` and runs
the full local check. Once the Release check has passed, it pushes a signed
release commit and `vX.Y.Z` tag together.

### What the workflow does

The workflow runs CI, native Linux qualification and release validation,
builds the native archive, pushes the `amd64` and `arm64` image by digest,
scans and signs it, attaches SBOMs and provenance, and smoke-tests both
platforms. Only then does it add the container tags (`X.Y.Z`, `X.Y`, `X` and
`latest`) and create the GitHub release, whose notes are the version's
changelog section followed by the image digest.

If the run fails before that, fix the workflow on `main` and run **Release**
from `main` with the tag as input; it rebuilds the tagged source. Never move
or reuse a published version: publish a patch release to fix a bad one.

GHCR signatures go to the `ghcr.io/autogitr/overture-signatures` package. The
workflow verifies the GHCR image and its signature without credentials, as a
user would, so it stops when either package is private. A package created by
the workflow can start private: make it public once and rerun the failed job.

Never delete untagged versions of the `overture` package: a release is an
index with one image and one attestation manifest per platform, and only the
index is tagged.

## Repository settings

Protect `main` and `v*` tags, require only the `ci-result` check, which passes
once every CI job a change needs has passed, and keep Actions permissions
read-only by default. CodeQL runs only when analysed code changes, so it is
not a required check.

Repository labels are defined in `.github/labels.json`. Preview changes with
`uv run --locked python -m scripts.sync_labels`; use `--apply` to reconcile them
or `--check` to detect drift.

## Documentation deployment

The **Docs** workflow in Overture builds the site on every pull request that
touches it and deploys it on `main`. It also runs when OvertureDB's own
**Docs** workflow dispatches it after a change to `OvertureDB/docs/`, weekly
as a safety net, and on demand. OvertureDB builds the site on its own pull
requests too, so a broken page is caught before it is merged on either side.

For the dispatch, the OvertureDB GitHub App is installed on the Overture
repository with contents write access; the workflow uses the same
`OVERTUREDB_CLIENT_ID` and `OVERTUREDB_APP_PRIVATE_KEY` secrets as the
catalog automation.

GitHub Pages deploys from GitHub Actions.

## Brand assets

Run `bun run generate:brand --sync-db` from `frontend/` to regenerate both
products and copy every OvertureDB export to the sibling checkout's
`.github/brand/`. Without `--sync-db`, only Overture's checkout is updated.

`frontend/scripts/generate-brand.ts` owns the palettes, exact mark geometry,
optical sizes and layout. The wordmarks and approved tagline are outlined SVGs
in `frontend/design/`; exported mark SVGs in that directory are generated. The
tagline is **Artwork, collections & themes**. Outlined text needs no fonts on
the browser or build machine.

### Exports

- `*-logo`: the full-size mark, tightly bounded at its natural aspect ratio.
- `*-logo-inline`, `*-logo-stacked`, `*-banner`: measured, centred layouts.
- `*-dark` / `*-light`: explicit palettes for the corresponding backgrounds,
  available as SVG and PNG. Unsuffixed SVGs adapt to the host colour scheme.
- `*-tab.svg`: an optically tuned mark with 1.25px strokes at 16px height;
  PNG versions use square 16, 32 and 48px canvases. Prism keeps its regular
  hexagon proportions, so square canvases have equal space on the left and
  right.
- `favicon.svg`: Overture's square tab SVG; PNG fallbacks cover 16 and 32px.
- PWA icons use the complete square canvas. Maskable icons keep the mark
  inside the 80%-diameter safe circle; Apple icons use an opaque background
  and 10% inset. These backgrounds fill the canvas, and the mark insets
  protect it from device cropping. Social cards keep intentional space around
  the logo.

Composite assets use the painted text bounds, preserve aspect ratios, and
centre the icon and text block vertically or horizontally as appropriate.
Spacing between parts is intentional; there is no additional transparent
border around the composite. Do not stretch Prism to fill a square.

The app caches only the brand assets it uses. Full export sets remain
available for repository headers and other uses without bloating the offline
cache. This site serves them from `frontend/public/brand/` too, so a
regeneration updates the docs as well.
