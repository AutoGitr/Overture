import { afterEach, describe, expect, it, vi } from "vitest";
import { client } from "../../../generated/rest/client.gen";
import {
  deleteCollectionTheme,
  getSettings,
  logout,
  updateBackupSchedule,
} from "../../../generated/rest/sdk.gen";
import { sdkData } from "../../../lib/rest/sdk";
import {
  ApiError,
  overtureFetch,
  resetTransportSession,
  setUnauthorizedHandler,
} from "../../../lib/rest/transport";
import { mockFetch } from "../../helpers/fetch";

describe("REST transport", () => {
  afterEach(() => {
    client.setConfig({ baseUrl: location.origin });
    setUnauthorizedHandler(null);
    resetTransportSession();
  });

  it("sends credentials for reads", async () => {
    const { calls } = mockFetch({});

    await overtureFetch("/api/settings");

    expect(calls[0]?.init.credentials).toBe("include");
  });

  it("adds csrf to mutating requests when the cookie exists", async () => {
    document.cookie = "overture_csrf=csrf-token; path=/";
    const { calls } = mockFetch({});

    await overtureFetch("/api/settings", { method: "PUT" });

    expect(new Headers(calls[0]?.init.headers).get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("omits csrf when the cookie is absent", async () => {
    const { calls } = mockFetch({});

    await overtureFetch("/api/settings", { method: "PUT" });

    expect(new Headers(calls[0]?.init.headers).has("X-CSRF-Token")).toBe(false);
  });

  it("reports session expiry and preserves the request ID for authenticated failures", async () => {
    const expired = vi.fn();
    setUnauthorizedHandler(expired);
    mockFetch(
      { detail: "token expired" },
      { status: 401, headers: { "X-Request-ID": "request-1" } },
    );

    await expect(overtureFetch("/api/auth/me")).rejects.toMatchObject({
      message: "Your session has expired. Please sign in again.",
      status: 401,
      requestId: "request-1",
    });
    expect(expired).toHaveBeenCalledOnce();
  });

  it("keeps a failed sign-in local to the login form", async () => {
    const expired = vi.fn();
    setUnauthorizedHandler(expired);
    mockFetch({ detail: "Invalid credentials" }, { status: 401 });
    await expect(overtureFetch("/api/auth/login", { method: "POST" })).rejects.toMatchObject({
      status: 401,
    });
    expect(expired).not.toHaveBeenCalled();
  });

  it("represents network failures without exposing browser diagnostics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("token=private at https://private.test")),
    );
    await expect(overtureFetch("/api/settings")).rejects.toMatchObject({
      status: 0,
      message: "Could not reach Overture. Check your connection and try again.",
      retryable: true,
    });
  });

  it.each(["/api/settings", "/api/auth/me", "/api/auth/config"])(
    "discards a late unauthorized response after the session has changed: %s",
    async (path) => {
      const expired = vi.fn();
      setUnauthorizedHandler(expired);
      let respond!: (response: Response) => void;
      const response = new Promise<Response>((resolve) => {
        respond = resolve;
      });
      vi.stubGlobal(
        "fetch",
        vi.fn(() => response),
      );
      const request = overtureFetch(path);
      const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
      resetTransportSession();
      respond(new Response(null, { status: 401 }));
      await rejected;
      expect(expired).not.toHaveBeenCalled();
    },
  );

  it("honors caller cancellation without converting it to a network error", async () => {
    const controller = new AbortController();
    controller.abort();
    const { fetchMock } = mockFetch({});
    await expect(
      overtureFetch("/api/settings", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uses a safe fallback for non-JSON proxy failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>private upstream</html>", { status: 502 })),
    );
    await expect(overtureFetch("/api/settings")).rejects.toMatchObject({
      message: "Overture is unavailable. Please try again.",
      status: 502,
    });
  });

  it("limits support references to bounded identifiers", () => {
    expect(new ApiError("error", 500, "token=secret").requestId).toBeNull();
    expect(new ApiError("error", 500, "x".repeat(65)).requestId).toBeNull();
    expect(new ApiError("error", 403).retryable).toBe(false);
  });

  it("redacts sensitive response details before throwing", async () => {
    mockFetch({ detail: "failed with token=super-secret&password=hunter2" }, { status: 500 });

    await expect(overtureFetch("/api/settings")).rejects.toThrow(
      "failed with token=[REDACTED]&password=[REDACTED]",
    );
  });

  it("normalizes validation arrays into readable messages", async () => {
    mockFetch(
      {
        detail: [
          { loc: ["body", "cron_expression"], msg: "Invalid cron expression" },
          { loc: ["body", "retention", "latest"], msg: "Input should be greater than 0" },
        ],
      },
      { status: 422 },
    );

    await expect(sdkData(updateBackupSchedule({ body: {}, throwOnError: true }))).rejects.toThrow(
      "body.cron_expression: Invalid cron expression; body.retention.latest: Input should be greater than 0",
    );
  });

  it("preserves 204 responses for generated parsing", async () => {
    mockFetch({}, { status: 204 });

    await expect(sdkData(logout({ throwOnError: true }))).resolves.toBeNull();
  });

  it("uses generated path and query encoding", async () => {
    client.setConfig({ baseUrl: location.origin });
    const { calls } = mockFetch({ status: "ok" });

    await sdkData(
      deleteCollectionTheme({
        path: { collection_id: "plex://collection/Action & Adventure" },
        query: { media_type: "movie" },
        throwOnError: true,
      }),
    );

    expect(calls[0]?.url).toBe(
      "/api/collections/plex%3A%2F%2Fcollection%2FAction%20%26%20Adventure/theme?media_type=movie",
    );
  });

  it("supports generated reads through the configured transport", async () => {
    const { calls } = mockFetch({ workflow: "themes" });
    client.setConfig({ baseUrl: location.origin });

    const settings = await sdkData(getSettings({ throwOnError: true }));

    expect(settings).toMatchObject({ workflow: "themes" });
    expect(calls[0]?.url).toBe("/api/settings");
  });
});
