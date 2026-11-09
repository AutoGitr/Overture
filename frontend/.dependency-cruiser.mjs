/** Import rules for the layout AGENTS.md describes. */
const VIEWS = "^src/lib/(components|popups|router/pages)/";

/** @type {import('dependency-cruiser').IConfiguration} */
export default {
  forbidden: [
    {
      // Pages load through dynamic imports, which is what lets every view
      // reach the typed router, so only static imports can form a cycle.
      name: "no-static-cycles",
      severity: "error",
      // CriteriaEditor renders its own nested groups.
      from: { pathNot: "CriteriaEditor[.]svelte$" },
      to: { circular: true, viaOnly: { dependencyTypesNot: ["dynamic-import", "type-only"] } },
    },
    {
      name: "state-and-helpers-never-import-views",
      severity: "error",
      from: { path: "^src/lib/(utils|stores|rest|realtime|auth)/" },
      to: { path: VIEWS },
    },
    {
      name: "only-the-router-imports-pages",
      severity: "error",
      from: { path: "^src/lib/(components|popups)/" },
      to: { path: "^src/lib/router/pages/" },
    },
    {
      name: "the-rest-layer-knows-only-the-contract",
      severity: "error",
      from: { path: "^src/lib/rest/" },
      to: { path: "^src/lib/(components|popups|realtime|stores|router)/" },
    },
  ],
  options: {
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.app.json" },
    doNotFollow: { path: "node_modules" },
    exclude: { path: "^src/(generated|test)/" },
    enhancedResolveOptions: { extensions: [".ts", ".svelte", ".js", ".svelte.ts"] },
  },
};
