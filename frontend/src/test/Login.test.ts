import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Login from "../Login.svelte";
import { session } from "../lib/auth/session.svelte";
import { ApiError } from "../lib/rest/transport";
import { renderWithQueryClient } from "./helpers/render";

const login = vi.hoisted(() => vi.fn());

vi.mock("../generated/rest/sdk.gen", () => ({ login }));

describe("Login", () => {
  beforeEach(() => {
    session.config = {
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    window.history.replaceState(null, "", "/");
    login.mockResolvedValue({ data: { authenticated: true } });
  });

  it("shows only the configured SSO button and preserves the deep link", () => {
    session.config = {
      auth_mode: "oidc",
      oidc_enabled: true,
      display_name: "Continue with Authentik",
      auto_login: false,
    };
    window.history.replaceState(null, "", "/shows/42-example/art");
    renderWithQueryClient(Login, { onLogin: vi.fn() });
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continue with Authentik" })).toHaveAttribute(
      "href",
      "/api/auth/oidc/login?return_to=%2Fshows%2F42-example%2Fart",
    );
  });

  it("moves a signed-out deep link to the login page and returns to it after sign-in", async () => {
    window.history.replaceState(null, "", "/shows/42-example/art?season=1");
    const onLogin = vi.fn(() => {
      expect(window.location.pathname + window.location.search).toBe(
        "/shows/42-example/art?season=1",
      );
    });
    renderWithQueryClient(Login, { onLogin });
    expect(window.location.pathname + window.location.search).toBe(
      "/login?return_to=%2Fshows%2F42-example%2Fart%3Fseason%3D1",
    );

    await fireEvent.input(screen.getByLabelText("Password"), { target: { value: "password" } });
    await fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledOnce());
  });

  it("renders both the password form and the OIDC button in both mode", () => {
    session.config = {
      auth_mode: "both",
      oidc_enabled: true,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    window.history.replaceState(null, "", "/shows/42-example/art");
    renderWithQueryClient(Login, { onLogin: vi.fn() });
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toHaveClass("btn-primary");
    const ssoLink = screen.getByRole("link", { name: "Sign in with SSO" });
    expect(ssoLink).toHaveClass("btn-primary");
    expect(ssoLink).toHaveAttribute(
      "href",
      "/api/auth/oidc/login?return_to=%2Fshows%2F42-example%2Fart",
    );
  });

  it("auto-redirects to OIDC in both mode when auto_login is enabled", () => {
    window.history.replaceState(null, "", "/shows/42-example/art");
    const replace = vi.fn();
    vi.stubGlobal("location", { ...window.location, replace });
    session.config = {
      auth_mode: "both",
      oidc_enabled: true,
      display_name: "Sign in with SSO",
      auto_login: true,
    };
    renderWithQueryClient(Login, { onLogin: vi.fn() });
    expect(replace).toHaveBeenCalledWith(
      "/api/auth/oidc/login?return_to=%2Fshows%2F42-example%2Fart",
    );
    vi.unstubAllGlobals();
  });

  it("renders neither password form nor OIDC button in none mode", () => {
    session.config = {
      auth_mode: "none",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    renderWithQueryClient(Login, { onLogin: vi.fn() });
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Sign In" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in with SSO" })).not.toBeInTheDocument();
  });

  it("offers SSO retry and consumes only fixed error messages", () => {
    session.config = {
      auth_mode: "oidc",
      oidc_enabled: true,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    window.history.replaceState(null, "", "/?auth_error=oidc_denied");
    renderWithQueryClient(Login, { onLogin: vi.fn() });
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in with SSO" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("denied by your identity provider");
    expect(window.location.search).toBe("");
  });

  it("requires a password before submitting", () => {
    renderWithQueryClient(Login, { onLogin: vi.fn() });

    expect(document.querySelector('input[type="text"]')).toBeNull();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "Sign in with SSO" })).not.toBeInTheDocument();
  });

  it("uses the shared plain-text brand", () => {
    renderWithQueryClient(Login, { onLogin: vi.fn() });

    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("Over\u00e8ture");
  });

  it("calls the login API and parent callback on success", async () => {
    const onLogin = vi.fn();
    renderWithQueryClient(Login, { onLogin });

    await fireEvent.input(screen.getByLabelText("Password"), {
      target: { value: "password" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

    expect(login).toHaveBeenCalledWith({
      body: { password: "password" },
      throwOnError: true,
    });
    await waitFor(() => expect(onLogin).toHaveBeenCalled());
  });

  it("maps a rejected password to a generic credential error", async () => {
    login.mockRejectedValue(new ApiError("Not authenticated", 401));
    renderWithQueryClient(Login, { onLogin: vi.fn() });

    await fireEvent.input(screen.getByLabelText("Password"), {
      target: { value: "wrong" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Sign In" }));

    expect(await screen.findByText("Invalid credentials")).toBeInTheDocument();
  });

  it("announces a server failure and lets the user try signing in again", async () => {
    login.mockRejectedValueOnce(new ApiError("Server unavailable", 503));
    const onLogin = vi.fn();
    renderWithQueryClient(Login, { onLogin });
    await fireEvent.input(screen.getByLabelText("Password"), { target: { value: "password" } });
    await fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Server unavailable");
    expect(onLogin).not.toHaveBeenCalled();
    await fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
    await waitFor(() => expect(onLogin).toHaveBeenCalledOnce());
  });
});
