---
sidebar_position: 6
title: Documentation
description: How this site is built from both repositories and deployed.
---

# Documentation

This site is built with [Docusaurus](https://docusaurus.io/) from `docs/` in
the Overture repository and deployed to GitHub Pages at
`autogitr.github.io/Overture`. It documents both products, and each
repository owns its own pages:

| Pages      | Source                                                         | Site path             |
| ---------- | -------------------------------------------------------------- | --------------------- |
| Overture   | `Overture/docs/overture/`                                      | `/overture/`          |
| OvertureDB | `OvertureDB/docs/`                                             | `/overturedb/`        |
| Changelog  | `Overture/.github/CHANGELOG.md`, copied by `bun run changelog` | `/overture/changelog` |

OvertureDB's pages are read from the sibling checkout, `../OvertureDB`, the
same layout the contract scripts use. There is no copy and no submodule: the
deploy workflow checks both repositories out and builds once. Set
`OVERTUREDB_DOCS` to another path, relative to `docs/`, when the checkout
lives elsewhere.

## Writing

Pages are Markdown with front matter. A `.md` file is CommonMark, as GitHub
renders it; a `.mdx` file may use components such as tabs. Admonitions
(`:::note`, `:::warning`) and Mermaid diagrams work in both. Order pages with
`sidebar_position` and folders with `_category_.json`; a folder's `index.md`
is its landing page.

Write for the person running Overture or contributing to OvertureDB: what it
does and how to use it, in the present tense, never how it was built or what
it used to do. Link between the two sets with site paths
(`/overturedb/contributing`), and within a set with relative file paths, so
links are checked.

## Preview

```sh
cd docs
bun install --frozen-lockfile
bun run start        # http://localhost:3000/Overture/
```

Before committing, run `bun run ci` in `docs/`: it type-checks, checks
formatting and builds the site. The build fails on a broken link or anchor in
either set of pages.

## Deployment

The **Docs** workflow in Overture builds the site on every pull request that
touches it and deploys it on `main`. It also runs when OvertureDB's own
**Docs** workflow dispatches it after a change to `OvertureDB/docs/`, weekly
as a safety net, and on demand. OvertureDB builds the site on its own pull
requests too, so a broken page is caught before it is merged on either side.

For the dispatch, the OvertureDB GitHub App is installed on the Overture
repository with contents write access; the workflow uses the same
`OVERTUREDB_CLIENT_ID` and `OVERTUREDB_APP_PRIVATE_KEY` secrets as the
catalog automation.
