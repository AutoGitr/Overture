import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RegisterSWOptions } from "virtual:pwa-register";

const pwa = vi.hoisted(() => ({
  options: null as RegisterSWOptions | null,
  activate: vi.fn(() => Promise.resolve()),
}));

vi.mock("virtual:pwa-register", () => ({
  registerSW: (options: RegisterSWOptions) => {
    pwa.options = options;
    return pwa.activate;
  },
}));

async function freshUpdate() {
  vi.resetModules();
  const { appUpdate } = await import("../../../lib/stores/appUpdate.svelte");
  return appUpdate;
}

function serviceWorker(update: () => Promise<void> = () => Promise.resolve()) {
  return { update: vi.fn(update), waiting: null } as unknown as ServiceWorkerRegistration;
}

describe("appUpdate", () => {
  beforeEach(() => {
    pwa.options = null;
    pwa.activate.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("looks for an update when the server runs another version or restarted", async () => {
    const appUpdate = await freshUpdate();
    appUpdate.register();
    const registration = serviceWorker();
    pwa.options?.onRegisteredSW?.("/sw.js", registration);

    appUpdate.observeServer(__APP_VERSION__, false);
    expect(registration.update).not.toHaveBeenCalled();

    // A restart may bring a build of the same version.
    appUpdate.observeServer(__APP_VERSION__, true);
    appUpdate.observeServer("99.0.0", false);
    expect(registration.update).toHaveBeenCalledTimes(2);
    expect(appUpdate.available).toBe(false);

    pwa.options?.onNeedRefresh?.();
    expect(appUpdate.available).toBe(true);
    Object.assign(registration, { waiting: {} });
    await appUpdate.apply();
    expect(pwa.activate).toHaveBeenCalledOnce();
  });

  it("offers a reload when the server runs another version and no service worker serves the page", async () => {
    const appUpdate = await freshUpdate();
    appUpdate.register();
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });

    appUpdate.observeServer(__APP_VERSION__, true);
    expect(appUpdate.available).toBe(false);

    appUpdate.observeServer("99.0.0", false);
    expect(appUpdate.available).toBe(true);
    await appUpdate.apply();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("waits for service worker registration before checking for an update", async () => {
    vi.stubGlobal("navigator", { serviceWorker: {} });
    const appUpdate = await freshUpdate();
    appUpdate.register();

    appUpdate.observeServer("99.0.0", false);
    expect(appUpdate.available).toBe(false);

    const registration = serviceWorker();
    pwa.options?.onRegisteredSW?.("/sw.js", registration);
    expect(registration.update).toHaveBeenCalledOnce();
    expect(appUpdate.available).toBe(false);
  });

  it("ignores a failed update check; the next snapshot retries", async () => {
    const appUpdate = await freshUpdate();
    appUpdate.register();
    const registration = serviceWorker(() => Promise.reject(new Error("offline")));
    pwa.options?.onRegisteredSW?.("/sw.js", registration);

    appUpdate.observeServer(__APP_VERSION__, true);
    await Promise.resolve();

    expect(registration.update).toHaveBeenCalledOnce();
    expect(appUpdate.available).toBe(false);
  });

  it("offers a reload when the browser refuses the service worker", async () => {
    vi.stubGlobal("navigator", { serviceWorker: {} });
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    const appUpdate = await freshUpdate();
    appUpdate.register();

    // A restart of the same version needs nothing without a worker.
    appUpdate.observeServer(__APP_VERSION__, true);
    pwa.options?.onRegisterError?.(new Error("blocked"));
    expect(appUpdate.available).toBe(false);

    appUpdate.observeServer("99.0.0", false);
    expect(appUpdate.available).toBe(true);
    await appUpdate.apply();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("offers a reload for a version the server named before the worker was refused", async () => {
    vi.stubGlobal("navigator", { serviceWorker: {} });
    const appUpdate = await freshUpdate();
    appUpdate.register();

    appUpdate.observeServer("99.0.0", false);
    expect(appUpdate.available).toBe(false);
    pwa.options?.onRegisterError?.(new Error("blocked"));
    expect(appUpdate.available).toBe(true);
  });
});
