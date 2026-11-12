/**
 * Writes `overture/changelog.md` from the repository's changelog, so the site
 * shows the same file the releases are cut from. The copy is git-ignored.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const source = resolve(root, "../.github/CHANGELOG.md");
const target = resolve(root, "overture/changelog.md");

const frontMatter = `---
sidebar_position: 7
description: Every release of Overture, newest first.
custom_edit_url: https://github.com/AutoGitr/Overture/edit/main/.github/CHANGELOG.md
---

`;
writeFileSync(target, frontMatter + readFileSync(source, "utf8"));
