import { getPublicDatasetStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { afterEach, describe, expect, it, vi } from "vitest";
import { session } from "../../../lib/auth/session.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { overtureFetch, reportUnauthorized } from "../../../lib/rest/transport";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetch } from "../../helpers/fetch";

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  stop = undefined;
});

describe("session", () => {
  it("keeps an unavailable session distinct from an unauthenticated one and retries", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("unavailable"));
    expect(session.error).toContain("Could not reach Overture");
    mockFetch({
      authenticated: true,
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    await session.check();
    expect(session.phase).toBe("authenticated");
    expect(session.error).toBe("");
  });

  it("uses the server's unauthenticated result in password mode", async () => {
    mockFetch({
      authenticated: false,
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("anonymous"));
  });

  it("bypasses authentication when auth_mode is none", async () => {
    mockFetch({
      authenticated: false,
      auth_mode: "none",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("authenticated"));
    // Logout and expire are no-ops in none mode
    await session.logout();
    expect(session.phase).toBe("authenticated");
    session.expire();
    expect(session.phase).toBe("authenticated");
  });

  it("clears authenticated caches, popups, and jobs on expiry", async () => {
    mockFetch({
      authenticated: true,
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("authenticated"));
    queryClient.setQueryData(["private"], "private data");
    uiState.openPopupByName("settings");
    syncState.markStartAccepted();
    mockFetch({ detail: "Session expired" }, { status: 401 });
    await expect(overtureFetch("/api/settings")).rejects.toMatchObject({ status: 401 });
    expect(session.phase).toBe("anonymous");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    expect(uiState.openPopup).toBeNull();
    expect(syncState.running).toBe(false);
    expect(queryClient.getQueryData(getPublicDatasetStatusOptions().queryKey)).toBeUndefined();
    expect(session.error).toBe("");
  });

  it("ignores a superseded authentication check after sign-in", async () => {
    let respond!: (response: Response) => void;
    const response = new Promise<Response>((resolve) => {
      respond = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => response),
    );
    stop = session.start();
    session.signedIn();
    respond(
      Response.json({
        authenticated: false,
        auth_mode: "password",
        oidc_enabled: false,
        display_name: "Sign in with SSO",
        auto_login: false,
      }),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(session.phase).toBe("authenticated");
  });

  it("stays anonymous when the authentication check itself returns 401", async () => {
    mockFetch({ detail: "Invalid token" }, { status: 401 });
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("anonymous"));
    expect(session.error).toBe("");
  });

  it("isolates logout from old requests and revocation notifications", async () => {
    mockFetch({ authenticated: true });
    stop = session.start();
    await vi.waitFor(() => expect(session.phase).toBe("authenticated"));
    window.history.replaceState(null, "", "/shows/42-example/art");
    queryClient.setQueryData(["private"], "private data");
    let respond!: (response: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          respond = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const stale = overtureFetch("/api/settings");
    const staleRejected = expect(stale).rejects.toMatchObject({ name: "AbortError" });
    const respondStale = respond;
    const loggingOut = session.logout();
    await session.logout();
    expect(session.phase).toBe("logging-out");
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(window.location.pathname + window.location.search).toBe("/login?autologin=0");
    respondStale(new Response(null, { status: 401 }));
    await staleRejected;
    reportUnauthorized();
    expect(session.phase).toBe("logging-out");
    respond(Response.json({ status: "ok", redirect_url: "/login?autologin=0" }));
    await loggingOut;
    expect(session.phase).toBe("anonymous");
  });

  it.each([true, false])(
    "checks server state after an uncertain logout (authenticated=%s)",
    async (authenticated) => {
      mockFetch({ authenticated: true });
      stop = session.start();
      await vi.waitFor(() => expect(session.phase).toBe("authenticated"));
      mockFetch({ detail: "Logout unavailable" }, { status: 503 });
      await session.logout();
      expect(session.phase).toBe("unavailable");
      expect(session.error).toContain("Logout unavailable");
      expect(window.location.search).toBe("?autologin=0");
      mockFetch({
        authenticated,
        auth_mode: "oidc",
        oidc_enabled: true,
        auto_login: true,
        display_name: "SSO",
      });
      await session.check();
      expect(session.phase).toBe(authenticated ? "authenticated" : "anonymous");
    },
  );
});
