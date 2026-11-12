---
sidebar_position: 5
title: Releases
description: How a version is cut, qualified, signed and published.
---

# Releases

Maintainers only. Pushing a `vX.Y.Z` tag triggers the **Release** workflow,
which qualifies the tag and publishes after the `release` environment approves
it. Overture follows [Semantic Versioning](https://semver.org/):

- **PATCH** (`1.0.x`): Backward-compatible fixes (`fix:`, `perf:`, `deps:`).
- **MINOR** (`1.x.0`): Backward-compatible new features or settings (`feat:`).
- **MAJOR** (`x.0.0`): Breaking database, API, or environment changes
  (`feat!:`, `BREAKING CHANGE:`).

## Cutting a release

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
`[Unreleased]` entries of the changelog under `## [X.Y.Z] - <date>` and runs
the full local check. Once the Release check has passed, it pushes a signed
release commit and `vX.Y.Z` tag together.

## What the workflow does

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
read-only by default. CodeQL analyses only the languages a change touches, so
it is not a required check.

GitHub Pages deploys from GitHub Actions; see
[Documentation](documentation.md).
