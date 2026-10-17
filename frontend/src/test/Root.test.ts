import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Root from "../Root.svelte";
import { mockFetch } from "./helpers/fetch";

describe("application session screen", () => {
  it("shows the connection failure rather than the login form, then retries", async () => {
    mockFetch(
      { detail: "Service unavailable" },
      { status: 503, headers: { "X-Request-ID": "boot-request" } },
    );
    render(Root);
    expect(await screen.findByRole("alert")).toHaveTextContent("boot-request");
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    mockFetch({
      authenticated: false,
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    await fireEvent.click(screen.getByRole("button", { name: "Retry connection" }));
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });

  it("rechecks an unavailable session when the browser reconnects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(Root);
    await screen.findByRole("button", { name: "Retry connection" });
    const { fetchMock } = mockFetch({
      authenticated: false,
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    });
    await fireEvent(window, new Event("online"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
  });
});
