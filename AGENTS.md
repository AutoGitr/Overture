# Agent guide

Write correct, secure, fully typed, tested and minimal code, following each
framework's best practice through the skills below. Setup and commands are in
[Contributing](docs/overture/developer/contributing.md).
`scripts/pre-commit-check.sh` enforces every rule a check can; this guide holds
only the ones that need judgment.

## Repositories

- **Overture** (this repository): FastAPI backend in `src/overture/` with its
  tests in `tests/`, Svelte frontend in `frontend/`, native packaging in
  `packaging/linux/`, documentation site in `docs/` (Overture's pages in
  `docs/overture/`; OvertureDB's are read from `../OvertureDB/docs/`).
- **OvertureDB**: the curated catalog, checked out as `../OvertureDB`. Its
  `schema/` is the catalog contract and `data/` holds the entries.

The two never drift:

- Edit the contract in `../OvertureDB/schema/`, then copy it with
  `scripts.catalog_contract`. Rules both apply are imported from it, never
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

## Engineering standards

- **Root cause first.** Fix problems where they originate; no wrappers or
  defensive fallbacks around code that should be corrected.
- **Minimal code.** No helper or abstraction with a single user. Prefer
  deleting code to adding it.
- **One source of truth.** Business rules live in the backend; the frontend
  reads them from the generated contracts. Before adding a component, constant
  or mapping, find the one that exists and extend it. A constant names one
  limit: a second limit gets its own, even at the same value. A concern that
  must stay in one place gets an entry in a homes test.
- **Secure by default.** Remote fetches go through the private-address guards
  (`utils/ssrf.py`, `utils/image_fetch.py`), errors and logs through
  `sanitise_error`; credentials never reach URLs, responses or the browser.
- **Data is never lost.** Never delete the only copy of something before its
  replacement is verified.

## Comments and documentation

Write for someone reading the code as it is now. History belongs in commit
messages and the changelog.

- **Describe the present.** Never say what code used to do or what a fix fixed
  ("no longer", "previously", "the new"). A test name says what holds.
- **Comment the why, not the what:** an outside constraint, a non-obvious
  invariant, or why the obvious approach is wrong. Rename or restructure
  instead of explaining unclear code. No author tags.
- **Docstrings** state in one present-tense line what a module, class or
  function is or returns; add `Raises:` or argument notes only when a caller
  needs them. Document a field (`#:` in Python, `/** */` in TypeScript) when
  its meaning, unit or `None` case is not obvious.
- **Docs follow the code.** A change to behaviour, settings or the API updates
  `docs/overture/` in the same task, written for the person running Overture.
  A catalog change updates `../OvertureDB/docs/` too.

## Backend

- `routers/` parse and authorise a request and call one service. `services/`
  own the rules, transactions and their effects, and a feature package keeps
  each responsibility in its own class.
- Keep write transactions short: `Database.write_session()` serialises every
  writer behind SQLite's write lock.
- Effects others observe (broadcasts, scheduler registration, waking download
  workers through `DownloadService.committed(session)`) happen after the
  commit. Work over many rows commits per item or per `CHUNK_SIZE` chunk.
- An operation's working rows go in a scratch database (`utils/scratch.py`).

### Database migrations

- A new stored format converts existing rows with the rule the app uses,
  including JSON copies in `saved_schedules.payload` and `job_results.payload`.
- Implement `downgrade()`, or say in it why data stays. The migration's test
  in `test_migrations.py` seeds the previous revision with rows as the app
  stores them.
- The databases in `tests/fixtures/databases/` are what releases wrote;
  `scripts/release.sh` adds them, and they are never edited.

## Frontend

- Views live in `lib/router/` (pages), `lib/components/` and `lib/popups/`
  (opened through `popups/registry.ts`); client state in `lib/stores/`; pure
  helpers and `.svelte.ts` classes in `lib/utils/`; `lib/realtime/` applies
  WebSocket events. `src/test/` mirrors `src/`.
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
  network and collaborators a test is not about.
- Test components through their props and find elements by role or label. Run
  `bun run test:e2e` after changing layout or styles, and refresh a snapshot
  only for a change you meant.
- When a guard fails, fix the cause. Raise a budget or limit only for a change
  that earns it, and never the ESLint complexity limit. Add a new write path
  or background operation to `OPERATIONS` in `test_workloads.py`. An
  exception a guard allows names why.

## Environment and finishing

- Always `uv run ...` and Bun (never `.venv`, bare `python`, `pip`, `npm`,
  `npx`, `yarn`, `pnpm` or `bun --bun`). Leave staging and commits to the
  user; never push.
- A change users notice adds one line under `## Unreleased` in
  `.github/CHANGELOG.md`, as `- **Area:** What changed.`, written for the
  person running Overture, under the section it belongs to (a change that asks
  something of the reader is 🚨 Breaking Changes); skip refactors, tests and CI, and never edit
  released sections. Within an area, put what matters most first.
- Before finishing, run `scripts/pre-commit-check.sh --fix` (and OvertureDB's
  when it changed) and `bun run ci` in `docs/` when docs changed. End with a
  Conventional Commits message.
