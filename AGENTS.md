# Agent guide

Write production-quality code: correct, secure, fully typed, tested, minimal and
idiomatic for the versions pinned here. Follow the established best practice of
each framework and library, using the skills below; where this guide is silent,
that practice applies. Leave every file you touch at least as clean as you found
it.

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
  `src/overture/services/public_dataset/schema/`; never edit the copy.
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

Run `npx` commands that skills show through Bun (`bunx playwright cli`,
`bunx @sveltejs/mcp svelte-autofixer <file>`).

`.agents/skills.json` lists every skill and subagent with its source, and
`uv run python -m scripts.sync_skills` installs them into `.agents/skills/`,
`.claude/skills/` and `.claude/agents/`:

- Skills shipped inside dependencies follow the lockfiles; run the sync after a
  dependency update.
- GitHub skills are pinned to a commit; `--update` moves them to the latest one.
- `svelte-query` is Overture's own skill and is edited in `.agents/skills/`.
  Every other installed copy is generated; never edit it.
- `--check` fails when a copy differs from its source or a skill is not listed.

## Engineering standards

- **Root cause first.** Fix problems where they originate. No wrappers, defensive
  fallbacks or patch layers around code that should be corrected.
- **Minimal code.** No unnecessary abstractions, dead code, redundant helpers or
  boilerplate. Prefer deleting code to adding it; an abstraction needs more than
  one real user.
- **One source of truth.** Define every rule, constant and mapping once and
  import it. Business rules live in the backend; the frontend uses the generated
  contracts and leaves validation to the API.
- **Secure by default.** Remote fetches go through the private-address guards
  (`src/overture/utils/ssrf.py` and the image fetch helpers), errors and logs
  pass through `sanitise_error`, and credentials never reach URLs, responses or
  the browser.
- **Tested.** Every behaviour change comes with tests at the level where the
  behaviour lives. Tests are deterministic and never touch the real network or
  DNS. Fix a failing test by fixing the code or updating it to the new intent,
  never by weakening it.
- **Comments explain why**: an invariant, a security boundary or an upstream
  quirk. Never narrate the code or its history. Docstrings are one line unless
  a caller needs more.
- **Suppressions.** `# noqa`, `# type: ignore` and `# pyright: ignore` only for an
  external constraint that cannot be typed or refactored away. Name the exact
  code and say why in a comment. File-category exemptions belong in
  `per-file-ignores` in `pyproject.toml`.
- **Pure ASCII source.** Code and config files contain no curly quotes, en or em
  dashes or look-alike Unicode. Write non-ASCII test data as escapes
  (`"\u00e9"`), and non-ASCII markup as entities (`&middot;`).

## Backend

### Layers

- `routers/` parse and authorise a request and call one service; they never open
  a session or hold business rules.
- `services/` own the rules, the transactions and what happens after them.
  `runtime.py` builds them and is the only place that wires them together.
- `repositories/` run queries against the session they are given; they never
  commit.
- `db/models/` hold the tables, `schemas/` the API contracts and `ws/events.py`
  the registry of WebSocket events.

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

### Python

- Pyright strict mode covers `src/` and `tests/`; `scripts/` and `packaging/`
  are linted by Ruff only.
- Use built-in generics, `X | None`, PEP 695 generics (`def f[T]()`,
  `type Alias = ...`) and unparenthesised multi-exception clauses where there is
  no `as` (`except TypeError, ValueError:`).
- Module-level imports are `lazy` (Ruff enforces it), so there are no
  `TYPE_CHECKING` blocks. Annotations are deferred natively (PEP 649); never add
  `from __future__ import annotations`. Use `sentinel("NAME")` for sentinel
  values and `re.prefixmatch`/`re.fullmatch` rather than `re.match`. Text I/O is
  UTF-8 by default; pass `encoding=` only for anything else.
- Choose data structures for their access pattern: `set`/`dict` for membership,
  `deque` for queues (never `list.pop(0)`), `tuple`/`frozenset` for immutable
  values and keys, `frozendict` for constant mappings. Prefer comprehensions to
  append loops.
- Model data by role: `StrictBaseModel` (`src/overture/schemas/base.py`) for API
  contracts, `@dataclass(slots=True, frozen=True)` for internal values,
  `NamedTuple` for small records, and closed unions over open protocols when
  the set of cases is known.

## Frontend

### Layout

- `src/generated/` holds the contracts generated from the backend; never edit
  it. Talk to the backend only through its REST client and query helpers.
- `lib/rest/` holds the query client and its cache policy (`queryClient.ts`) and
  the cache helpers (`cache.ts`); `lib/realtime/` applies WebSocket events to the
  cache and to stores.
- `lib/router/` holds the routes and their pages; `lib/components/`,
  `lib/popups/` (opened through `popups/registry.ts`) and feature folders such as
  `components/operations/` hold the views.
- `lib/stores/` holds client state and realtime projections; `lib/utils/` holds
  pure helpers and `.svelte.ts` classes.
- `src/test/` mirrors `src/`, with shared helpers in `src/test/helpers/`.

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

### Components

- **Split by responsibility**, not by how often a component is used. A part
  becomes its own component when it has its own state or queries, needs a
  `{#key}` boundary to start over, loads lazily as a route or popup, or is worth
  testing alone. Fold a small stateless component that only passes props on
  into its parent, or into a snippet.
- Move form and business logic into a `.svelte.ts` class or a `.ts` module,
  where it can be tested without rendering, and pass that object to the view
  instead of long lists of callbacks.
- Props are typed with `$props()`; callback props are named `on...`. Use
  `$bindable` only for a form control's value. Keep a component generic
  (`generics="T extends string"`) rather than widening a union to `string`.
- Use the `class={[...]}` and `class={{ ... }}` forms rather than `class:`
  directives.

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

### TypeScript

- No `as` casts or `!` assertions where the types can say it: Svelte types
  `event.currentTarget` in handlers, generic components keep unions typed, and
  type guards or lookups narrow unknown values. A cast that bridges an untyped
  browser or library API says so in a comment.

## Tests

- Backend tests use the real services against the test database from
  `tests/conftest.py`; replace only the network and the collaborators a test is
  not about.
- Run frontend unit tests with `bun run test:unit`. Vitest runs on Node where
  it is installed, as in CI; never force Bun's runtime with `bun --bun`, since
  jsdom then fails to start in the Linux fork workers.
- Test a component through its props, and render the page or popup when the
  behaviour is how the parts work together. Find elements by role or label,
  never by class or generated id.
- Run `bun run test:e2e` after changing layout or styles; it checks desktop and
  mobile.

## Database migrations

Every change that needs a migration must ship with one:

- **Schema changes:** any model change. Autogenerate against a database at head,
  then review it.
- **Data changes:** any change to how stored values are written or read (a new
  format, a renamed enum value, moved or merged data) converts the existing
  rows, including copies held elsewhere, such as the JSON in
  `saved_schedules.payload` and `job_results.payload`. Never leave old rows for
  runtime code to tolerate.
- Convert with the rule the application uses (for example the vendored
  contract), so migrated rows equal what the app now writes.
- Chain from the current head and implement `downgrade()`, or explain in it why
  data stays as it is. Add a test to `tests/test_database/test_migrations.py`
  that seeds the previous revision.

## Environment

- The machine runs Windows with PowerShell: chain commands with `;`, not `&&`.
  Run shell scripts with Git Bash
  (`& "C:\Program Files\Git\bin\bash.exe" <script>`); bare `bash` is the WSL
  stub, which cannot see `uv` or `bun`.
- Always `uv run ...`; never activate `.venv`, run bare `python` or use `pip`.
  Change dependencies with `uv add` and `uv remove`.
- Bun only; never `npm`, `npx`, `yarn` or `pnpm`.
- Leave staging and commits to the user unless asked, and never push or
  otherwise publish to a remote.

## Changelog

`.github/CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and becomes the release notes.

- A change users notice adds an entry under `## [Unreleased]` in the same
  commit: behaviour, settings, API, database, packaging, security fixes and
  dependency updates that fix something. Skip refactors, tests, CI and
  contributor docs.
- File it under `### Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` or
  `Security`, and write one line for the person running Overture: what changed
  for them and what they must do, not how it was implemented.
- Never edit released sections; `scripts/release.sh` moves `[Unreleased]`
  under the new version.

## Before finishing

- Run `scripts/pre-commit-check.sh --fix`. It formats, regenerates the
  contracts, then runs every check CI runs on what changed.
- When OvertureDB changed, also run its `scripts/pre-commit-check.sh`.
- Update the README for behaviour changes.
