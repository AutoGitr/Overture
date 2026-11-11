import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Header from "../../../lib/components/Header.svelte";
import { session } from "../../../lib/auth/session.svelte";
import { matchState, themeJobState } from "../../../lib/stores/bulkJobState.svelte";
import { getPublicDatasetStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { appSettings, realtimeSnapshot } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

function browseCatalog(enabled: boolean) {
  settingsState.load(appSettings({ overturedb_browse: true }));
  queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, {
    ...realtimeSnapshot().public_dataset_status,
    enabled,
  });
}

describe("Header", () => {
  beforeEach(() => {
    session.config = {
      auth_mode: "password",
      oidc_enabled: false,
      display_name: "Sign in with SSO",
      auto_login: false,
    };
    queryClient.clear();
    browseCatalog(false);
    uiState.closePopup();
    uiState.mobileShowDetail = false;
    matchState.reset();
    themeJobState.reset();
  });

  it("opens primary workflow popups from toolbar buttons", async () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    await fireEvent.click(screen.getByTitle("Assets"));
    expect(uiState.openPopup).toBe("operations");
    expect(uiState.operationsTab).toBe("assets");

    await fireEvent.click(screen.getByTitle("Sync"));
    expect(uiState.openPopup).toBe("operations");
    expect(uiState.operationsTab).toBe("sync");
  });

  it.each([true, false])(
    "offers OvertureDB in the menu only while it is enabled (%s)",
    async (enabled) => {
      browseCatalog(enabled);
      renderWithQueryClient(Header, { onLogout: vi.fn() });
      await fireEvent.click(screen.getByLabelText("Open menu"));
      expect(!!screen.queryByRole("button", { name: "OvertureDB" })).toBe(enabled);
    },
  );

  it("links the brand to the landing page with a full reload", () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    expect(screen.getByRole("heading", { name: "Overture" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Overture" });
    expect(link).toHaveAttribute("href", "/");
    // Any target attribute makes sv-router skip the click, so the browser reloads.
    expect(link).toHaveAttribute("target", "_self");
  });

  it("opens the overflow menu on mouse hover only, and a click does not pin it", async () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

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
    renderWithQueryClient(Header, { onLogout: vi.fn() });

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
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");

    await fireEvent.keyDown(document, { key: "Escape" });
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("opens overflow popups and closes the menu", async () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    await fireEvent.click(screen.getByText("Settings"));

    expect(uiState.openPopup).toBe("settings");
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("opens stats popup from overflow menu and closes the menu", async () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    const menu = screen.getByLabelText("Open menu");
    await fireEvent.click(menu);
    await fireEvent.click(screen.getByText("Statistics"));

    expect(uiState.openPopup).toBe("stats");
    expect(menu).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles mobile detail/sidebar state", async () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    await fireEvent.click(screen.getByLabelText("Toggle sidebar"));

    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("delegates logout to the session owner", async () => {
    const onLogout = vi.fn();
    renderWithQueryClient(Header, { onLogout });

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
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    await fireEvent.click(screen.getByLabelText("Open menu"));
    expect(screen.queryByText("Logout")).not.toBeInTheDocument();
  });

  it("offers OvertureDB beside the brand only while the catalog can be browsed", () => {
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    expect(screen.queryByRole("switch", { name: "Browse OvertureDB" })).toBeNull();
  });

  it("switches the sidebar between the library and OvertureDB, and the brand with it", async () => {
    browseCatalog(true);
    settingsState.load(
      appSettings({
        overturedb_browse: true,
        media_server: "jellyfin",
        collections_supported: true,
      }),
    );
    await navigate("/collections");
    renderWithQueryClient(Header, { onLogout: vi.fn() });

    const browse = screen.getByRole("switch", { name: "Browse OvertureDB" });
    expect(browse).not.toBeChecked();
    await fireEvent.click(browse);
    // The mode carries over to where the catalog has it.
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections"));
    expect(screen.getByRole("link", { name: "OvertureDB" })).toHaveAttribute("href", "/");
    expect(browse).toBeChecked();

    await fireEvent.click(browse);
    await vi.waitFor(() => expect(route.pathname).toBe("/collections"));
    expect(screen.getByRole("link", { name: "Overture" })).toBeInTheDocument();
  });
});
