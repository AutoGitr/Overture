---
sidebar_position: 3
title: Generated files
description: What is generated, from what, and the command that regenerates it.
---

# Generated files

- **API contracts.** After changing endpoints, schemas, WebSocket events or
  setting defaults, run `uv run python -m scripts.contracts`. It regenerates
  `openapi/overture.json` and `frontend/src/generated/`; commit them with your
  change.
- **Media server specs.** `scripts/provider_specs.py` pins the Plex, Jellyfin
  and Emby API specs by version and digest. A changed upstream spec fails
  until you review it and update the pin.
- **OvertureDB contract.** Edit it in `../OvertureDB/schema/`, then copy it
  here with `uv run python -m scripts.catalog_contract ../OvertureDB`. CI
  fails while the copy differs.
- **Preset schema and vocabulary.** `preset.schema.json` and
  `preset-vocabulary.json` in the contract are generated from Overture's
  collection models. After changing a criteria field, operator, source, set
  dimension or the portable file models, run
  `uv run python -m scripts.preset_contract ../OvertureDB`, then copy the
  contract back with `scripts.catalog_contract`. CI in both repositories fails
  while they differ, or while an OvertureDB preset is one Overture cannot add.
- **Database migrations.** After changing a model in `src/overture/db/models/`,
  run `uv run alembic revision --autogenerate -m "<summary>"`, review the
  result and add a test in `tests/test_database/test_migrations.py`.
  Migrations run when Overture starts.
- **Brand assets.** The repository owner regenerates them; see
  [MAINTAINING.md](https://github.com/AutoGitr/Overture/blob/main/.github/MAINTAINING.md#brand-assets).
- **Agent skills.** `uv run python -m scripts.sync_skills` installs the skills
  listed in `.agents/skills.json`; skills an installed package ships are copied
  from it and git-ignored, so run it again after a dependency update.
- **Native archive.** Build it with
  `docker buildx build --platform linux/amd64 --target native-artifact --output type=local,dest=dist .`
  The `native.yml` workflow tests it with `packaging/linux/test.sh`.
