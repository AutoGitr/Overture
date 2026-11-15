---
sidebar_position: 6
title: Documentation
description: How this site is built from both repositories and previewed.
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
