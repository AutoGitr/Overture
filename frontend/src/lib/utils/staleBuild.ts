import { readJson, writeJson } from "./storage";

/** Where a tab notes the build it reloaded from, so it reloads once per build. */
const RELOADED_FROM = "staleBuild_reloadedFrom";

/**
 * Load the current build when a page asks for a file an update removed.
 *
 * Each build names its files by their contents, so a tab opened before
 * Overture was updated asks for files the new build no longer has. Reloading
 * fetches the new build; a build whose own files fail is left to show the
 * error, so a file truly missing never reloads the tab over and over.
 *
 * @param build Names the running build, such as the URL of its entry file.
 */
export function reloadOnStaleBuild(target: Window, build: string) {
  // Vite reports a failed dynamic import on the window; this runs before any
  // component, and lives as long as the page.
  target.addEventListener("vite:preloadError", (event) => {
    if (readJson<string | null>(RELOADED_FROM, null, "session") === build) return;
    writeJson(RELOADED_FROM, build, "session");
    event.preventDefault();
    target.location.reload();
  });
}
