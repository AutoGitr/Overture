# Agent guide

Write correct, secure, fully typed, tested and minimal code, following each
framework's best practice through the skills below. Setup, commands and
workflow are in [CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Repositories

- **Overture** (this repository): FastAPI backend in `src/overture/` with its
  tests in `tests/`, Svelte frontend in `frontend/`, native packaging in
  `packaging/linux/`, documentation site in `docs/` (Overture's pages in
  `docs/overture/`; OvertureDB's are read from `../OvertureDB/docs/`).
- **OvertureDB**: the curated catalog, checked out as `../OvertureDB`. Its
  `schema/` is the authoritative catalog contract and `data/` holds the entries.

The two never drift:

- Edit the contract only in `../OvertureDB/schema/` and copy it into
  `src/overture/catalog_contract/`. Rules both apply (entry validation, the
  catalog format, canonical artwork links) are imported from it, never
  re-implemented.
- A change on one side that affects the other is finished on both sides in the
  same task: code, tests, `data/` entries, docs and issue templates. Bump
  `SCHEMA_VERSION` when the other side cannot read the change as it stands.

## Skills

Read the matching skill before working in its area and follow it. Run `npx`
commands from skills as `bunx`.

| Work                                                       | Skill                                                                                                              |
| ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| FastAPI routes, dependencies, responses, SSE               | `fastapi`                                                                                                          |
| SQLModel models, sessions and queries                      | `sqlmodel`                                                                                                         |
| Python dependencies, lockfile, running tools               | `uv`                                                                                                               |
| Ruff configuration and lint findings                       | `ruff`                                                                                                             |
| Svelte components and `.svelte.ts` modules                 | `svelte-core-bestpractices`, `svelte-code-writer` (in Claude Code, the `svelte-file-editor` subagent applies both) |
| Server data, mutations and the query cache in the frontend | `svelte-query`                                                                                                     |
| Unit and component tests                                   | `vitest`                                                                                                           |
| End-to-end tests and browser checks                        | `playwright-best-practices`, `playwright-cli`                                                                      |
| Failed end-to-end runs                                     | `playwright-trace`                                                                                                 |

`uv run python -m scripts.sync_skills` installs the skills in
`.agents/skills.json` (run it again after a dependency update); only
`.agents/skills/svelte-query` is edited by hand.

## Engineering standards

- **Root cause first.** Fix problems where they originate; no wrappers or
  defensive fallbacks around code that should be corrected.
- **Minimal code.** No dead code, redundant helpers or abstractions with a
  single user. Prefer deleting code to adding it.
- **One source of truth.** Define every rule, constant and mapping once.
  Business rules live in the backend; the frontend uses the generated
  contracts. A low-level concern has one home in `utils/`
  (`tests/test_architecture/test_homes.py` lists them); a new one gets its own
  module, named for what it does.
- **Secure by default.** Remote fetches go through the private-address guards
  (`utils/ssrf.py`, `utils/image_fetch.py`), errors and logs through
  `sanitise_error`; credentials never reach URLs, responses or the browser.
- **Data is never lost.** A file Overture keeps is written with
  `utils.file.staged_file`. Never delete the only copy of something before its
  replacement is verified.

## Comments and documentation

Write for someone reading the code as it is now. History belongs in commit
messages and the changelog.

- **Describe the present.** Never say what code used to do or what a fix fixed
  ("no longer", "previously", "the new"). A test name says what holds.
- **Comment the why, not the what:** an outside constraint, a non-obvious
  invariant, or why the obvious approach is wrong. Rename or restructure
  instead of explaining unclear code.
- **Docstrings** state in one present-tense line what a module, class or
  function is or returns; add `Raises:` or argument notes only when a caller
  needs them. Document a field (`#:` in Python, `/** */` in TypeScript) when
  its meaning, unit or `None` case is not obvious.
- **No noise:** no TODOs, commented-out code or author tags. A suppression
  (`noqa`, `pyright: ignore`, `eslint-disable`) names its rule and says why.
- **Docs follow the code.** A change to behaviour, settings or the API updates
  `docs/overture/` in the same task, written for the person running Overture.
  A catalog change updates `../OvertureDB/docs/` too.

## Backend

- `routers/` parse and authorise a request and call one service. `services/`
  own the rules, transactions and their effects; `runtime.py` alone wires them
  together, and a feature package keeps each responsibility in its own class.
  `repositories/` query the session they are given and never commit.
  `test_layers.py` holds which layer may import which.
- `Database.write_session()` serialises every writer behind SQLite's write
  lock: keep transactions short, with no network, file I/O or hashing inside;
  run blocking work with `owned_thread`. Take asset locks before opening a
  write session, never inside one.
- Effects others observe (broadcasts, scheduler registration, waking download
  workers through `DownloadService.committed(session)`) happen after the
  commit. Work over many rows commits per item or per `CHUNK_SIZE` chunk.
- Overture's database is reached through SQLModel sessions; an operation's
  working rows go in a scratch database (`utils/scratch.py`).

### Database migrations

- Any model change ships a migration: autogenerate at head, then review.
- A new stored format converts existing rows with the rule the app uses,
  including JSON copies in `saved_schedules.payload` and `job_results.payload`.
- Implement `downgrade()`, or say in it why data stays. Add a test to
  `test_migrations.py` that seeds the previous revision with rows as the app
  stores them. `test_release_upgrades.py` also upgrades the databases every
  release wrote; `scripts/release.sh` adds them, and they are never edited.

## Frontend

- `src/generated/` holds the generated contracts; never edit it. Talk to the
  backend only through `lib/rest/`; `lib/realtime/` applies WebSocket events.
- Views live in `lib/router/` (pages), `lib/components/` and `lib/popups/`
  (opened through `popups/registry.ts`); client state in `lib/stores/`; pure
  helpers and `.svelte.ts` classes in `lib/utils/`. `src/test/` mirrors `src/`.
- **One owner per piece of state.** Server data lives in the query cache; what
  is open lives in the URL (`routes.ts`); stores hold only client state and
  realtime projections. Route pages own their queries and pass data as props.
- **Effects only reach outside** (timers, the DOM, navigation, network, a
  store, seeding a form draft once). Derive instead of copying into `$state`;
  use a writable `$derived` for local state that resets with its inputs.
  Listen with `<svelte:window>` and `<svelte:document>`.
- **Styles are scoped to the component that renders the markup.** `app.css`
  holds only tokens and app-wide utilities. A parent adjusts a child through
  CSS custom properties; `:global` appears only beneath the component's own
  element. A responsive override sits next to the rule it changes.

## Tests

- Backend tests use the real services and test database, replacing only the
  network and collaborators a test is not about; they never touch the real
  network or DNS.
- Frontend: `bun run test:unit` (never `bun --bun`); test components through
  their props and find elements by role or label. Run `bun run test:e2e` after
  changing layout or styles.
- The guards (`tests/conftest.py`, `tests/test_architecture/`,
  `tests/test_release/`, `.dependency-cruiser.mjs`, `check-bundle.ts`,
  `performance.spec.ts`) fail a change that costs more or crosses a layer: fix
  the cause, and raise a budget only for a change that earns it. Add a new
  write path or background operation to `OPERATIONS` in `test_workloads.py`.

## Environment and finishing

- Always `uv run ...` and Bun (never `.venv`, bare `python`, `pip`, `npm`,
  `npx`, `yarn` or `pnpm`). Leave staging and commits to the user; never push.
- A change users notice adds one line under `## Unreleased` in
  `.github/CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/)),
  as `- **Area:** What changed.`, written for the person running Overture; skip
  refactors, tests and CI, and never edit released sections. Within an area,
  put what matters most first; the pre-commit check orders the rest.
- Before finishing, run `scripts/pre-commit-check.sh --fix` (and OvertureDB's
  when it changed) and `bun run ci` in `docs/` when docs changed. End with a
  Conventional Commits message.
