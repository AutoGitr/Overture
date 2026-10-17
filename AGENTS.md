# Agent guide

Write production-quality code: correct, secure, fully typed, tested, minimal and
idiomatic for the versions pinned here. Follow the established best practice of
each framework and library, using the skills below; where this guide is silent,
that practice applies. Leave every file you touch at least as clean as you found it.

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
`bunx @sveltejs/mcp`).

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
  boilerplate. Prefer deleting code to adding it.
- **One source of truth.** Define every rule, constant and mapping once and
  import it. Business rules live in the backend; the frontend uses the generated
  contracts and leaves validation to the API.
- **Secure by default.** Remote fetches go through the private-address guards
  (`src/overture/utils/ssrf.py` and the image fetch helpers), errors and logs pass
  through `sanitise_error`, and credentials never reach URLs, responses or the
  browser.
- **Tested.** Every behaviour change comes with tests at the level where the
  behaviour lives. Tests are deterministic and never touch the real network or
  DNS. Fix a failing test by fixing the code or updating it to the new intent,
  never by weakening it.
- **Compatibility.** Keep settings and the API compatible within a major version.
  Migrate stored data rather than adding runtime fallbacks for old data shapes.
- **Comments explain why**: an invariant, a security boundary or an upstream
  quirk. Never narrate the code or its history.
- **Suppressions.** `# noqa`, `# type: ignore` and `# pyright: ignore` only for an
  external constraint that cannot be typed or refactored away. Name the exact
  code and say why in a comment. File-category exemptions belong in
  `per-file-ignores` in `pyproject.toml`.
- **Pure ASCII source.** Code and config files contain no curly quotes, en or em
  dashes or look-alike Unicode. Write non-ASCII test data as escapes (`"\u00e9"`).

## Python

- Pyright strict mode covers `src/` and `tests/`; `scripts/` and `packaging/`
  are linted by Ruff only.
- Use built-in generics, `X | None`, PEP 695 generics (`def f[T]()`,
  `type Alias = ...`) and unparenthesised multi-exception clauses where there is
  no `as` (`except TypeError, ValueError:`).
- Module-level imports are `lazy` (Ruff enforces it), so there are no
  `TYPE_CHECKING` blocks. Annotations are deferred natively (PEP 649); never add
  `from __future__ import annotations`. Use `sentinel("NAME")` for sentinel values and
  `re.prefixmatch`/`re.fullmatch` rather than `re.match`. Text I/O is UTF-8 by
  default; pass `encoding=` only for anything else.
- Choose data structures for their access pattern: `set`/`dict` for membership,
  `deque` for queues (never `list.pop(0)`), `tuple`/`frozenset` for immutable
  values and keys, `frozendict` for constant mappings. Prefer comprehensions to
  append loops.
- Model data by role: `StrictBaseModel` (`src/overture/schemas/base.py`) for API
  contracts, `@dataclass(slots=True, frozen=True)` for internal values,
  `NamedTuple` for small records.

## Frontend

- Svelte runes only (`$state`, `$derived`, `$props`, `$effect`); no `export let`,
  `$:`, `on:` directives or `<slot>`. Prefer `$derived` and event handlers to
  `$effect`.
- Talk to the backend through the generated REST client and TanStack Query;
  never hand-write request or response types or edit generated files.

## Database migrations

Every change that needs a migration ships with one:

- **Schema changes:** any model change. Autogenerate against a database at head,
  then review it.
- **Data changes:** any change to how stored values are written or read (a new
  format, a renamed enum value, moved or merged data) converts the existing
  rows, including copies held elsewhere, such as JSON snapshots in
  `download_jobs.selection_state` and `write_intent`. Never leave old rows for
  runtime code to tolerate.
- Convert with the rule the application uses (for example the vendored
  contract), so migrated rows equal what the app now writes.
- Chain from the current head and implement `downgrade()`, or explain in it why
  data stays as it is. Add a test to
  `tests/test_database/test_migrations.py` that seeds the previous
  revision.

## Environment

- The machine runs Windows with PowerShell: chain commands with `;`, not `&&`.
  Run shell scripts with Git Bash (`& "C:\Program Files\Git\bin\bash.exe" <script>`);
  bare `bash` is the WSL stub, which cannot see `uv` or `bun`.
- Always `uv run ...`; never activate `.venv`, run bare `python` or use `pip`.
  Change dependencies with `uv add` and `uv remove`.
- Bun only; never `npm`, `npx`, `yarn` or `pnpm`.
- Never push or otherwise publish to a remote. The user does that.

## Before finishing

- Run `scripts/pre-commit-check.sh`. If it regenerates contracts, stage them and
  run it again. The Git hook's `--quick` mode does not replace this.
- When OvertureDB changed, also run its `scripts/pre-commit-check.sh`.
- Update the README for behaviour changes.
