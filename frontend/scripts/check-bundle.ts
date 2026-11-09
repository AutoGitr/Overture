/** Fail the build when what a browser downloads grows past its budget. */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const ASSETS = fileURLToPath(new URL("../../src/overture/frontend/assets", import.meta.url));

/** Compressed kilobytes; raise one only for a change that earns the weight. */
const BUDGETS = { entry: 125, javascript: 225, css: 22 };

const compressed = (name: string) =>
  gzipSync(readFileSync(join(ASSETS, name)), { level: 9 }).length / 1024;
const total = (names: string[]) => names.reduce((sum, name) => sum + compressed(name), 0);

const files = readdirSync(ASSETS);
const scripts = files.filter((name) => name.endsWith(".js"));
const measured = {
  entry: total(scripts.filter((name) => name.startsWith("index-"))),
  javascript: total(scripts),
  css: total(files.filter((name) => name.endsWith(".css"))),
};

const over = Object.entries(BUDGETS).filter(
  ([name, budget]) => measured[name as keyof typeof measured] > budget,
);
for (const [name, budget] of Object.entries(BUDGETS)) {
  console.warn(`${name}: ${measured[name as keyof typeof BUDGETS].toFixed(1)} of ${budget} KB`);
}
if (over.length) {
  console.error(`Over budget: ${over.map(([name]) => name).join(", ")}`);
  process.exit(1);
}
