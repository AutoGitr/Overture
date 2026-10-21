/// <reference types="vitest/config" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

/** The backend the dev server proxies to (its container port). */
const BACKEND_URL = "http://localhost:5885";

/** Paths the backend owns; every other path is a frontend route. */
const BACKEND_PATHS = "^/(?:api|ws)(?:[/?]|$)";

export default defineConfig(({ mode }) => ({
  plugins: [
    svelte(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        id: "/",
        name: "Overture - Media Art & Theme Manager",
        short_name: "Overture",
        description: "Art and theme management for Plex, Jellyfin, and Emby",
        start_url: "/",
        scope: "/",
        display: "standalone",
        display_override: ["standalone", "minimal-ui"],
        orientation: "any",
        background_color: "#0a0c10",
        theme_color: "#0a0c10",
        categories: ["entertainment", "utilities"],
        icons: [
          {
            src: "/pwa-192x192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "/pwa-maskable-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
        shortcuts: [
          {
            name: "Movies",
            short_name: "Movies",
            url: "/movies",
            icons: [{ src: "/pwa-192x192.png", sizes: "192x192" }],
          },
          {
            name: "Shows",
            short_name: "Shows",
            url: "/shows",
            icons: [{ src: "/pwa-192x192.png", sizes: "192x192" }],
          },
        ],
      },
      workbox: {
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        skipWaiting: true,
        navigateFallback: "/index.html",
        // Workbox matches pathname + search; reserve query-bearing roots too.
        navigateFallbackDenylist: [new RegExp(BACKEND_PATHS, "i")],
        globPatterns: ["**/*.{html,js,css,svg,png,woff2}"],
        globIgnores: ["brand/*-dark.*", "brand/*-light.*", "og.png"],
      },
    }),
  ],
  server: {
    port: 5173,
    // The browser's Host is forwarded unchanged: without APP_URL the backend
    // accepts only a WebSocket Origin that matches it.
    proxy: {
      [BACKEND_PATHS]: { target: BACKEND_URL, ws: true },
    },
  },
  build: {
    // The backend package serves the build, so it is written into it.
    outDir: "../src/overture/frontend",
    emptyOutDir: true,
  },
  // Tests resolve Svelte's client build, as the browser does, in dev mode.
  resolve: mode === "test" ? { conditions: ["browser", "development"] } : undefined,
  test: {
    environment: "jsdom",
    include: ["src/test/**/*.test.ts"],
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
    unstubGlobals: true,
    unstubEnvs: true,
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,svelte}"],
      exclude: ["src/generated/**", "src/test/**", "src/main.ts", "**/*.d.ts"],
      thresholds: {
        lines: 94,
        statements: 92,
        functions: 91,
        branches: 82,
      },
    },
  },
}));
