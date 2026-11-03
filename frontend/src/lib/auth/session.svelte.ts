import { tick } from "svelte";
import { authConfig, logout, me } from "../../generated/rest/sdk.gen";
import { SIGNED_OUT_PATH } from "../../generated/settings";
import type { AuthConfig } from "../../generated/rest/types.gen";
import { resetRealtimeProjection } from "../realtime/projector";
import { realtimeTransport } from "../realtime/transport";
import { clearRestCache } from "../rest/queryClient";
import { sdkData } from "../rest/sdk";
import { resetTransportSession, setUnauthorizedHandler } from "../rest/transport";
import { settingsState } from "../stores/settingsState.svelte";
import { uiState } from "../stores/uiState.svelte";
import { errorMessage } from "../utils/errors";

type SessionPhase = "checking" | "authenticated" | "anonymous" | "unavailable" | "logging-out";

class Session {
  phase = $state<SessionPhase>("checking");
  error = $state("");
  config = $state<AuthConfig>({
    auth_mode: "password",
    oidc_enabled: false,
    display_name: "Sign in with SSO",
    auto_login: false,
  });
  private revision = 0;

  start(): () => void {
    setUnauthorizedHandler(() => this.expire());
    void this.check();
    return () => {
      setUnauthorizedHandler(null);
      this.revision++;
      this.clear();
      this.phase = "checking";
    };
  }

  async check(): Promise<void> {
    const revision = ++this.revision;
    this.phase = "checking";
    this.error = "";
    try {
      const signal = AbortSignal.timeout(15000);
      const [result, config] = await Promise.all([
        sdkData(me({ throwOnError: true, signal })),
        sdkData(authConfig({ throwOnError: true, signal })),
      ]);
      if (revision !== this.revision) return;
      this.config = config;
      if (config.auth_mode === "none" || result.authenticated) this.phase = "authenticated";
      else this.expire();
    } catch (error) {
      if (revision !== this.revision) return;
      this.error =
        error instanceof Error && error.name === "TimeoutError"
          ? "Overture did not respond. Please try again."
          : errorMessage(error, "Could not check your session. Please try again.");
      this.phase = "unavailable";
    }
  }

  signedIn(): void {
    this.revision++;
    this.clear();
    this.phase = "authenticated";
  }

  async logout(): Promise<void> {
    if (this.config.auth_mode === "none") return;
    if (this.phase === "logging-out") return;
    const revision = ++this.revision;
    this.phase = "logging-out";
    this.clear();
    // Unmount the authenticated router before replacing its URL.
    await tick();
    if (revision !== this.revision) return;
    window.history.replaceState(null, "", SIGNED_OUT_PATH);
    try {
      const result = await sdkData(
        logout({ throwOnError: true, signal: AbortSignal.timeout(15000) }),
      );
      if (revision !== this.revision) return;
      if (result.redirect_url === SIGNED_OUT_PATH) this.phase = "anonymous";
      else window.location.replace(result.redirect_url);
    } catch (error) {
      if (revision !== this.revision) return;
      // A lost response does not tell us whether the server revoked the session.
      // Retry the session check instead of restoring cached authenticated state.
      this.error = errorMessage(
        error,
        "Could not confirm logout. Please check your connection and retry.",
      );
      this.phase = "unavailable";
    }
  }

  expire(): void {
    if (this.config.auth_mode === "none") return;
    if (this.phase === "anonymous" || this.phase === "logging-out") return;
    this.revision++;
    this.phase = "anonymous";
    this.clear();
  }

  private clear(): void {
    resetTransportSession();
    realtimeTransport.disconnect();
    clearRestCache();
    resetRealtimeProjection();
    settingsState.reset();
    uiState.closePopup();
    uiState.searchQuery = "";
    uiState.mobileShowDetail = false;
    this.error = "";
  }
}

export const session = new Session();
