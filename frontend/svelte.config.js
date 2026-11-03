// @ts-check
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

/**
 * The single source of truth for Svelte compiler options.
 *
 * vite-plugin-svelte, svelte-check and eslint-plugin-svelte all read this file,
 * so `runes: true` applies to the build, the type check and the editor alike -
 * repeating it per tool config is how they drift apart.
 *
 * @type {import('@sveltejs/vite-plugin-svelte').SvelteConfig}
 */
export default {
  preprocess: vitePreprocess(),
  compilerOptions: {
    runes: true,
  },
};
