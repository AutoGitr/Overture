// @ts-check
import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import tseslint from "typescript-eslint";

// The package root re-exports every icon, and Vite compiles all of them
// for each test file and dev page that imports it.
const ICON_IMPORTS = {
  name: "@lucide/svelte",
  message: 'Import each icon from "@lucide/svelte/icons/<name>".',
};

/** @type {import('eslint').Linter.Config[]} */
export default [
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...svelte.configs["flat/recommended"],

  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
    },
  },

  // svelte-eslint-parser handles both .svelte component files and .svelte.ts/.svelte.js
  // module files (Svelte 5 rune stores). Without forwarding tseslint.parser here,
  // it defaults to plain JS parsing and chokes on TypeScript syntax like `import type`.
  {
    files: ["**/*.svelte", "**/*.svelte.ts"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },

  {
    rules: {
      // Override base JS rule with the TypeScript-aware version.
      // _ prefix exempts intentional ignores (e.g. `catch (_err)`, unused params).
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],

      "@typescript-eslint/no-explicit-any": "error",

      "no-console": ["error", { allow: ["error", "warn"] }],

      // Requests go through the generated SDK, so their paths and payloads
      // follow the backend contract; only the REST layer sends raw requests.
      "no-restricted-imports": [
        "error",
        {
          paths: [ICON_IMPORTS],
          patterns: [
            {
              group: ["**/rest/transport"],
              importNames: ["overtureFetch"],
              message: "Call the generated SDK from src/generated/rest instead.",
            },
          ],
        },
      ],
    },
  },

  {
    files: ["src/lib/rest/**", "src/test/**"],
    rules: {
      "no-restricted-imports": ["error", { paths: [ICON_IMPORTS] }],
    },
  },

  // An API path written by hand drifts from the routes it names; the REST
  // layer builds every one from the generated types.
  {
    files: ["src/**/*.ts", "src/**/*.svelte"],
    ignores: ["src/lib/rest/**", "src/test/**"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          // esquery ends a pattern at its first slash, so "/" is written \x2F.
          selector: String.raw`Literal[value=/^\x2Fapi(\x2F|$)/]`,
          message: "Build API paths in src/lib/rest from the generated types.",
        },
        {
          selector: String.raw`TemplateElement[value.raw=/^\x2Fapi(\x2F|$)/]`,
          message: "Build API paths in src/lib/rest from the generated types.",
        },
      ],
    },
  },

  // A promise nobody awaits loses its rejection; start background work with `void`.
  {
    files: ["src/**/*.ts", "src/**/*.svelte"],
    languageOptions: {
      parserOptions: {
        project: ["./tsconfig.app.json"],
        extraFileExtensions: [".svelte"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
    },
  },

  {
    files: ["src/test/**"],
    rules: {
      "no-console": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },

  {
    ignores: [
      "src/generated/**",
      "coverage/**",
      "node_modules/**",
      "test-results/**",
      "playwright-report/**",
    ],
  },
];
