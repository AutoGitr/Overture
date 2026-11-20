import { registerSW } from "virtual:pwa-register";

/**
 * Whether a newer Overture build than this tab's is out, and taking it up.
 *
 * The service worker keeps a tab's own build until the user reloads, so an
 * update never removes files an open tab still uses; it reports a waiting
 * update instead. Each realtime snapshot names the version the server runs:
 * another one means the tab no longer matches the server's API, and a
 * restart may have brought a build of the same version, so either makes the
 * tab look for the update at once.
 */
class AppUpdate {
  /** A newer version is ready; reloading takes it up. */
  available = $state(false);
  #activate: (() => Promise<void>) | null = null;
  #registration: ServiceWorkerRegistration | undefined;
  /** The browser refused the service worker, so a reload loads a new version. */
  #unregistered = false;
  #pendingCheck = false;
  /** The version the server last said it runs. */
  #serverVersion: string | null = null;

  /** Register the service worker; call once, when the app starts. */
  register(): void {
    this.#activate = registerSW({
      immediate: true,
      onNeedRefresh: () => (this.available = true),
      onRegisteredSW: (_url, registration) => {
        this.#registration = registration;
        if (this.#pendingCheck) {
          this.#pendingCheck = false;
          this.#checkForUpdate();
        }
      },
      // Some browsers refuse service workers, such as in private windows.
      onRegisterError: () => {
        this.#unregistered = true;
        this.#pendingCheck = false;
        if (this.#serverVersion !== null && this.#serverVersion !== __APP_VERSION__) {
          this.available = true;
        }
      },
    });
  }

  /**
   * Note the version the server runs, from a realtime snapshot, and whether
   * the server restarted since the last one.
   */
  observeServer(version: string, restarted: boolean): void {
    this.#serverVersion = version;
    if (version !== __APP_VERSION__) {
      // A page served without a service worker (plain HTTP has none) loads
      // the server's version by reloading.
      if (this.#hasServiceWorker()) this.#checkForUpdate();
      else this.available = true;
    } else if (restarted) {
      this.#checkForUpdate();
    }
  }

  #hasServiceWorker(): boolean {
    return (
      this.#registration !== undefined || (!this.#unregistered && "serviceWorker" in navigator)
    );
  }

  /** Ask the service worker to check for a newer build on the server. */
  #checkForUpdate(): void {
    if (!this.#registration) {
      this.#pendingCheck = !this.#unregistered;
      return;
    }
    // Ignore transient offline or restart errors; the next reconnect retries.
    void this.#registration.update().catch(() => {});
  }

  /** Reload into the newer version. */
  async apply(): Promise<void> {
    if (this.#registration?.waiting && this.#activate) await this.#activate();
    else location.reload();
  }
}

export const appUpdate = new AppUpdate();
