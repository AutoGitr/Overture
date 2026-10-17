import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Header from "../../../lib/components/Header.svelte";
import { session } from "../../../lib/auth/session.svelte";
import { matchState } from "../../../lib/stores/matchState.svelte";
import { themeJobState } from "../../../lib/stores/bulkJobState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";

describe("Header", () => {
  beforeEach(() => {
    session.config = {
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    uiState.closePopup();
    uiState.mobileShowDetail = false;
    matchState.reset();
    themeJobState.reset();
  });

  it("opens primary workflow popups from toolbar buttons", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    await fireEvent.click(screen.getByTitle("Assets"));
    expect(uiState.openPopup).toBe("operations");
    expect(uiState.operationsTab).toBe("assets");

    await fireEvent.click(screen.getByTitle("Sync"));
    expect(uiState.openPopup).toBe("operations");
    expect(uiState.operationsTab).toBe("sync");
  });

  it("links the brand to the landing page with a full reload", () => {
    render(Header, { props: { onLogout: vi.fn() } });

    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Overture" });
    expect(link).toHaveAttribute("href", "/");
    // Any target attribute makes sv-router skip the click, so the browser reloads.
    expect(link).toHaveAttribute("target", "_self");
  });

  it("opens the overflow menu on mouse hover only, and a click does not pin it", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    const menu = screen.getByLabelText("Open menu");
    const wrapper = menu.parentElement!;
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await fireEvent.pointerEnter(wrapper, { pointerType: "mouse" });
    expect(menu).toHaveAttribute("aria-expanded", "true");

    await fireEvent.pointerDown(menu, { pointerType: "mouse" });
    await fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");

    await fireEvent.pointerLeave(wrapper, { pointerType: "mouse" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(menu.querySelector(".lucide-x")).toBeNull();
  });

  it("toggles the overflow menu with a tap, since touch has no hover", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    const menu = screen.getByLabelText("Open menu");
    const wrapper = menu.parentElement!;

    // A tap reports enter and leave around the press; neither may move the menu.
    await fireEvent.pointerEnter(wrapper, { pointerType: "touch" });
    await fireEvent.pointerDown(menu, { pointerType: "touch" });
    await fireEvent.pointerLeave(wrapper, { pointerType: "touch" });
    await fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");

    await fireEvent.pointerDown(menu, { pointerType: "touch" });
    await fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await fireEvent.pointerDown(menu, { pointerType: "touch" });
    await fireEvent.click(menu);
    await fireEvent.pointerDown(document.body, { pointerType: "touch" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles the overflow menu from the keyboard and closes it on Escape", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");

    await fireEvent.keyDown(document, { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("opens overflow popups and closes the menu", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    await fireEvent.click(screen.getByText("Settings"));

    expect(uiState.openPopup).toBe("settings");
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("opens stats popup from overflow menu and closes the menu", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    await fireEvent.click(screen.getByText("Statistics"));

    expect(uiState.openPopup).toBe("stats");
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles mobile detail/sidebar state", async () => {
    render(Header, { props: { onLogout: vi.fn() } });

    await fireEvent.click(screen.getByLabelText("Toggle sidebar"));

    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("delegates logout to the session owner", async () => {
    const onLogout = vi.fn();
    render(Header, { props: { onLogout } });

    await fireEvent.click(screen.getByLabelText("Open menu"));
    await fireEvent.click(screen.getByText("Logout"));

    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("hides the logout button when auth_mode is none", async () => {
    session.config = {
      auth_mode: "none",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    render(Header, { props: { onLogout: vi.fn() } });

    await fireEvent.click(screen.getByLabelText("Open menu"));
    expect(screen.queryByText("Logout")).not.toBeInTheDocument();
  });
});
