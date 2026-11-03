import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../openapi/overture.json",
  output: {
    entryFile: false,
    path: "src/generated/rest",
  },
  parser: {
    hooks: {
      operations: {
        getKind: (operation) => {
          if (operation.method === "post" && operation.path === "/api/themes/search") {
            return ["query"];
          }
        },
      },
    },
  },
  plugins: [
    {
      name: "@hey-api/client-fetch",
      runtimeConfigPath: "./src/lib/rest/transport.ts",
    },
    "@hey-api/typescript",
    {
      name: "@hey-api/sdk",
    },
    {
      // Generates `<operation>Options` / `<operation>Mutation` helpers, plus
      // tagged query keys. `tags: true` puts the operation's OpenAPI tags into
      // the query key so `rest/cache.ts` can invalidate by domain.
      name: "@tanstack/svelte-query",
      queryKeys: {
        tags: true,
      },
    },
  ],
});
