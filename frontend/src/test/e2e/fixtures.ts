import { test as base, expect, type Page, type WebSocketRoute } from "@playwright/test";
import { appSettings, publicDatasetStatus as datasetStatus } from "../helpers/fixtures";

export { expect };

export const epoch = "e2e";
const publicDatasetStatus = datasetStatus();
export const realtimeSnapshot = {
  epoch,
  sequence: 0,
  server_time: new Date().toISOString(),
  jobs: [],
  downloads: [],
  public_dataset_status: publicDatasetStatus,
};

/** The app's live connection, driven from the test. */
export interface Realtime {
  emit(message: unknown): void;
  setSnapshot(snapshot: unknown): void;
  close(options: { code: number; reason: string }): Promise<void>;
}

/**
 * A signed-out backend holding one movie and one show. Every test starts with
 * it; a test overrides a route by registering its own, which takes precedence.
 */
export const test = base.extend<{ backend: void; realtime: Realtime }>({
  realtime: [
    async ({ page }, use) => {
      let snapshot: unknown = realtimeSnapshot;
      /** The app's latest connection. */
      let socket: WebSocketRoute | undefined;
      /** The connection that has its snapshot, and so takes live events. */
      let synced: WebSocketRoute | undefined;
      /** Events emitted before then, sent right after the snapshot, as the
       * server would order them. */
      const pending: string[] = [];
      let connected: (route: WebSocketRoute) => void;
      const firstConnection = new Promise<WebSocketRoute>((resolve) => {
        connected = resolve;
      });

      await page.routeWebSocket("**/ws", (route) => {
        socket = route;
        synced = undefined;
        connected(route);
        route.onMessage((data) => {
          if (JSON.parse(String(data)).event !== "client.resync") return;
          route.send(
            JSON.stringify({
              epoch,
              sequence: 0,
              event: "realtime.snapshot",
              data: snapshot,
            }),
          );
          synced = route;
          for (const message of pending.splice(0)) route.send(message);
        });
      });

      await use({
        setSnapshot: (value) => {
          snapshot = value;
        },
        emit: (message) => {
          const payload = JSON.stringify(message);
          if (synced) synced.send(payload);
          else pending.push(payload);
        },
        close: async (options) => {
          await (socket ?? (await firstConnection)).close(options);
        },
      });
    },
    { auto: true },
  ],
  backend: [
    async ({ page }, use) => {
      let authenticated = false;
      await page.route("**/api/auth/config", (route) =>
        route.fulfill({
          json: {
            auth_mode: "password",
            oidc_enabled: false,
            display_name: "Sign in with SSO",
            auto_login: false,
          },
        }),
      );
      await page.route("**/api/auth/me", (route) => route.fulfill({ json: { authenticated } }));
      await page.route("**/api/auth/login", (route) => {
        authenticated = true;
        return route.fulfill({ json: { authenticated: true } });
      });
      await page.route("**/api/auth/logout", (route) => {
        authenticated = false;
        return route.fulfill({ json: { status: "ok", redirect_url: "/login?autologin=0" } });
      });
      await page.route("**/api/library/items*", (route) => {
        const movies = new URL(route.request().url()).searchParams.get("media_type") === "movie";
        return route.fulfill({
          json: {
            items: [
              movies
                ? { id: 1, title: "Alien", media_type: "movie", year: 1979, monitored: true }
                : { id: 2, title: "Twin Peaks", media_type: "show", year: 1990, monitored: true },
            ],
            total: 1,
          },
        });
      });
      // A reload empties the query cache, so the open item is fetched on its own.
      await page.route("**/api/library/items/1", (route) =>
        route.fulfill({
          json: { id: 1, title: "Alien", media_type: "movie", year: 1979, monitored: true },
        }),
      );
      await page.route("**/api/settings", (route) =>
        route.fulfill({ json: appSettings({ workflow: "art", auto_match_art: false }) }),
      );
      await page.route("**/api/library/libraries?*", (route) => route.fulfill({ json: [] }));
      await page.route("**/api/bulk/assets/schedules", (route) => route.fulfill({ json: [] }));
      await page.route("**/api/media-server/libraries", (route) => route.fulfill({ json: [] }));
      await page.route("**/api/sync/schedules", (route) => route.fulfill({ json: [] }));
      await page.route("**/api/art/*/*/sources**", (route) =>
        route.fulfill({ json: { current_url: null, sources: {} } }),
      );
      await page.route("**/api/public-dataset/status", (route) =>
        route.fulfill({ json: publicDatasetStatus }),
      );
      await page.route("**/api/public-dataset/items/*/record", (route) =>
        route.fulfill({ json: { found: false } }),
      );
      await page.route("**/api/public-dataset/items/*/sources", (route) =>
        route.fulfill({ json: { found: false, item: null, seasons: [] } }),
      );
      await page.route("**/api/public-dataset/sync", (route) =>
        route.fulfill({ json: { status: "started" } }),
      );
      await page.route("**/api/realtime/snapshot", (route) =>
        route.fulfill({ json: realtimeSnapshot }),
      );
      await use();
    },
    { auto: true },
  ],
});

export async function logIn(page: Page, url = "/") {
  await page.goto(url);
  await page.getByLabel("Password").fill("password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(startupLoader(page)).toHaveCount(0);
}

export function startupLoader(page: Page) {
  return page.getByRole("status", { name: "Loading Overture" });
}

/** Assert the exact path, with no hash, once the app has navigated there. */
export async function assertRoute(page: Page, expectedPath: string) {
  await expect(page).toHaveURL(
    new RegExp(`${expectedPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`),
  );
  expect(new URL(page.url()).pathname).toBe(expectedPath);
  expect(new URL(page.url()).hash).toBe("");
}
