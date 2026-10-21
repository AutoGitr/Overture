import { readdir, readFile, rm } from "node:fs/promises";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createClient } from "@hey-api/openapi-ts";

import config from "../openapi-ts.config";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, "..");
const outputPath = resolve(frontendRoot, "src/generated/rest");
const checkOutputPath = resolve(frontendRoot, "src/generated/rest.check");
const check = process.argv.includes("--check");

async function filesIn(root: string, current = root): Promise<string[]> {
  const entries = await readdir(current, { withFileTypes: true }).catch(() => []);
  const files = await Promise.all(
    entries.map(async (entry) => {
      const path = resolve(current, entry.name);
      return entry.isDirectory() ? filesIn(root, path) : [relative(root, path)];
    }),
  );
  return files.flat().sort();
}

async function generatedOutputMatches(expected: string, actual: string): Promise<boolean> {
  const expectedFiles = await filesIn(expected);
  const actualFiles = await filesIn(actual);
  if (expectedFiles.join("\n") !== actualFiles.join("\n")) return false;

  for (const file of expectedFiles) {
    const [expectedContent, actualContent] = await Promise.all([
      readFile(resolve(expected, file)),
      readFile(resolve(actual, file)),
    ]);
    if (!expectedContent.equals(actualContent)) return false;
  }
  return true;
}

async function generate(path: string): Promise<void> {
  const resolvedConfig = await config;
  await createClient({
    ...resolvedConfig,
    logs: "silent",
    output: {
      ...(typeof resolvedConfig.output === "object" ? resolvedConfig.output : {}),
      clean: true,
      path,
    },
  });
}

if (check) {
  await rm(checkOutputPath, { force: true, recursive: true });
  try {
    await generate(checkOutputPath);
    if (!(await generatedOutputMatches(outputPath, checkOutputPath))) {
      console.error(`stale generated REST client: ${outputPath}`);
      process.exitCode = 1;
    }
  } finally {
    await rm(checkOutputPath, { force: true, recursive: true });
  }
} else {
  await generate(outputPath);
}
