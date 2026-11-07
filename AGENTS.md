# Agent guide

Write correct, secure, fully typed, tested and minimal code, following each
framework's best practice through the skills below.

Setup, commands and workflow are in [CONTRIBUTING.md](.github/CONTRIBUTING.md).
This file adds the rules for agents.

## Repositories

- **Overture** (this repository): FastAPI backend in `src/overture/` with its
  tests in `tests/`, Svelte frontend in `frontend/`, native packaging in
  `packaging/linux/`.
- **OvertureDB**: the curated catalog, checked out as `../OvertureDB`. Its
  `schema/` directory is the authoritative catalog contract and `data/` holds the
  entries.

The two never drift:

- Edit the contract only in `../OvertureDB/schema/` and copy it into
  `src/overture/dataset_contract/`; never edit the copy.
- Rules both projects apply (entry validation, the catalog format, canonical
  artwork links) live in the contract and are imported from it. Never
  re-implement them in either repository, the frontend or a script.
- A change on one side that affects the other is finished on both sides in the
  same task: code, tests, existing `data/` entries, docs and issue templates.
- Bump `SCHEMA_VERSION` when the other side cannot read a catalog change as it
  stands.

## Skills

Read the matching skill before working in its area and follow it.

| Work | Skill |
| --- | --- |
| FastAPI routes, dependencies, responses, SSE | `fastapi` |
| SQLModel models, sessions and queries | `sqlmodel` |
| Python dependencies, lockfile, running tools | `uv` |
| Ruff configuration and lint findings | `ruff` |
| Svelte components and `.svelte.ts` modules | `svelte-core-bestpractices`, `svelte-code-writer` (in Claude Code, the `svelte-file-editor` subagent applies both) |
| Server data, mutations and the query cache in the frontend | `svelte-query` |
| Unit and component tests | `vitest` |
| End-to-end tests and browser checks | `playwright-best-practices`, `playwright-cli` |
| Failed end-to-end runs | `playwright-trace` |

Run `npx` commands from skills as `bunx`.

`uv run python -m scripts.sync_skills` installs the skills listed in
`.agents/skills.json`; only `.agents/skills/svelte-query` is edited by hand.

## Engineering standards

- **Root cause first.** Fix problems where they originate; no wrappers or
  defensive fallbacks around code that should be corrected.
- **Minimal code.** No dead code, redundant helpers or abstractions with a
  single user. Prefer deleting code to adding it.
- **One source of truth.** Define every rule, constant and mapping once. Business
  rules live in the backend; the frontend uses the generated contracts.
- **Secure by default.** Remote fetches go through the private-address guards
  (`utils/ssrf.py`, image fetch helpers), errors and logs through
  `sanitise_error`; credentials never reach URLs, responses or the browser.
- **Tested.** Tests are deterministic and never touch the real network or DNS.

## Comments and documentation

Write for someone reading the code as it is now, with no knowledge of how it
got there. History belongs in commit messages and the changelog.

- **Describe the present.** Never mention what code used to do, what changed,
  what was removed or what a fix fixed (such as "no longer", "instead of the
  old", "previously", "fixed" or "the new"). A test name says what holds, not what
  was broken.
- **Comment the why, not the what.** Comment only what the code cannot say:
  an outside constraint (an API's rule, a server's quirk, a browser
  limitation), a non-obvious invariant, or why the obvious approach is wrong.
  Rename or restructure instead of explaining unclear code. Never restate a
  name, a type or the next line.
- **Docstrings** state what a module, class or function is or returns, in one
  line, in the present tense. Add a paragraph, `Raises:` or argument notes only
  when a caller needs them to use it correctly. Private helpers whose name says
  it all need none. TypeScript uses the same rules with `/** */` on exports and
  props whose meaning is not obvious from the type.
- **Fields.** Document a schema, model or prop field with `#:` (Python) or
  `/** */` (TypeScript) on the field when its meaning, unit or `None`/`null`
  case is not obvious from its name.
- **Placement.** A comment sits directly above the code it explains and stays
  true when that code moves. Section markers belong only in long stylesheets.
- **No noise.** No TODOs, commented-out code, author tags, ticket links without
  context, or apologies; open work goes in an issue.
- **Suppressions** (`noqa`, `pyright: ignore`, `eslint-disable`) name the exact
  rule and say why it does not apply, on the same line.
- **Docs follow the code.** A change to behaviour, settings or the API updates
  the README and docs in the same task, written for the person running
  Overture: what it does and how to use it, never how it was built.

## Backend

### Layers

- `routers/` parse and authorise a request and call one service; they never open
  a session or hold business rules.
- `services/` own the rules, the transactions and what happens after them.
  `runtime.py` builds them and is the only place that wires services together.
  A feature package with several parts (`collections/`, `art/`) keeps each
  responsibility in its own class; its service class only assembles them, and
  routers depend on the one part they call.
- `repositories/` run queries against the session they are given; they never
  commit.
- `db/models/` hold the tables, `schemas/` the API contracts and `ws/events.py`
  the registry of WebSocket events.
- Dependencies point inward: `routers` → `services` → `repositories` → `db`, and
  everything may use `domain`, `utils` and `dataset_contract`. `domain`,
  `utils`, `jobs`, `media_servers` and `repositories` never import `services`,
  and nothing below `main.py` takes `RuntimeServices`; inject the parts needed.

### Transactions and side effects

- `Database.write_session()` serialises every writer behind SQLite's single
  write lock, so keep write transactions short: no network calls, file I/O or
  hashing inside one. Run blocking work with `owned_thread`.
- Take asset locks (`AssetStorage.asset_locks`) before opening a write session,
  never inside one, and hold them only around work that must not overlap on the
  same item or collection.
- Effects other parts observe happen after the transaction commits: broadcasts,
  scheduler registration, and waking download workers through
  `DownloadService.committed(session)`. A failed transaction must leave none of
  them behind.
- Work over many rows commits per item or per bounded chunk (`CHUNK_SIZE`), so
  one failure rolls back only itself and the rest is counted.

## Frontend

### Layout

- `src/generated/` holds the generated contracts; never edit it. Talk to the
  backend only through the REST client and query helpers in `lib/rest/`;
  `lib/realtime/` applies WebSocket events to the cache and stores.
- Views live in `lib/router/` (pages), `lib/components/` and `lib/popups/`
  (opened through `popups/registry.ts`); client state in `lib/stores/`; pure
  helpers and `.svelte.ts` classes in `lib/utils/`. `src/test/` mirrors `src/`.

### State

- **One owner per piece of state.** Server data lives in the query cache. What
  is open, and in which view, lives in the URL: read it with `routedItem`,
  `routedItemId`, `routedCollectionId` and `routedItemView` from `routes.ts`.
  Stores hold only client state, such as UI preferences, and realtime
  projections.
- Route pages own the queries for what they show and pass the data down as
  props; never copy an entity into a store.
- **Effects only reach outside**: timers, the DOM, navigation, network calls,
  writing a store, or seeding a form draft once from server data. Never copy
  props or query data into `$state` with an effect: derive it, and use a
  writable `$derived` for local state that starts over when its inputs change.
- Listen to the window or document with `<svelte:window>` and
  `<svelte:document>`, never with `addEventListener` in an effect or `onMount`.

### Styles

- **Styles are scoped to the component that renders the markup.** Share a look
  by sharing a component that owns its styles. `app.css` holds only design
  tokens and app-wide utilities (`.btn`, `.option-card`, `.form-label`,
  `.text-muted` and the like).
- A parent adjusts a child through CSS custom properties the child reads
  (`<SegmentedControl --segmented-margin="0" />`).
- Use `:global` only beneath the component's own element: for markup a snippet
  passes in, or a class on an icon component. Never write a top-level `:global`
  rule, and never repeat a rule `app.css` already has.
- Keep a responsive override next to the rule it changes.

## Tests

- Backend tests use the real services and the test database; replace only the
  network and collaborators a test is not about.
- Run frontend unit tests with `bun run test:unit`; never force `bun --bun`
  (jsdom fails in the fork workers).
- Test components through their props; find elements by role or label.
- Run `bun run test:e2e` after changing layout or styles; it checks desktop and
  mobile.

## Database migrations

Every change that needs a migration must ship with one:

- **Schema changes:** any model change; autogenerate at head, then review.
- **Data changes:** a new stored format converts existing rows, including JSON
  copies in `saved_schedules.payload` and `job_results.payload`, with the rule
  the app uses, so migrated rows equal what the app now writes.
- Chain from the current head and implement `downgrade()`, or explain in it why
  data stays as it is. Add a test to `tests/test_database/test_migrations.py`
  that seeds the previous revision.

## Environment

- Always `uv run ...` (never `.venv`, bare `python` or `pip`); Bun only (never
  `npm`, `npx`, `yarn` or `pnpm`).
- Leave staging and commits to the user unless asked; never push.
- End every finished task with a Conventional Commits message
  ([CONTRIBUTING.md](.github/CONTRIBUTING.md)) in the final reply.

## Changelog

`.github/CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and becomes the release notes.

- A change users notice (behaviour, settings, API, database, packaging,
  security) adds one line under `## [Unreleased]` in the right Keep a Changelog
  heading, written for the person running Overture. Skip refactors, tests and
  CI. Never edit released sections.

## Before finishing

- Run `scripts/pre-commit-check.sh --fix`. It formats, regenerates the
  contracts, then runs every check CI runs on what changed.
- When OvertureDB changed, also run its `scripts/pre-commit-check.sh`.
- Update the README for behaviour changes.
