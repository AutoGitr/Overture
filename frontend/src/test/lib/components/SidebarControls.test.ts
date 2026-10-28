import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "svelte";
import SidebarControls from "../../../lib/components/SidebarControls.svelte";
import {
  searchFieldGroups,
  searchPlaceholder,
  sortMenu,
  type SidebarMode,
  type SidebarTab,
} from "../../../lib/utils/sidebarDomain";

interface ListOptions {
  mode?: SidebarMode;
  tab?: SidebarTab;
  tmdbConfigured?: boolean;
}

/** Renders the controls with the fields the sidebar passes for a list. */
function renderControls(props: Partial<ComponentProps<typeof SidebarControls>> & ListOptions = {}) {
  const { mode = "items", tab = "movie", tmdbConfigured = false, ...rest } = props;
  const searchField = rest.searchField ?? "title";
  const handlers = {
    onOpenFilters: vi.fn(),
    onSearchQueryChange: vi.fn(),
    onSearchFieldChange: vi.fn(),
    onSetSort: vi.fn(),
  };
  render(SidebarControls, {
    props: {
      section: `library:${tab}:${mode}`,
      searchGroups: searchFieldGroups("library", mode, tab, tmdbConfigured),
      placeholder: searchPlaceholder(mode, tab, searchField, 3),
      sortFields:
        searchField === "tmdb" ? [] : sortMenu(mode === "collections" ? "collections" : "library"),
      filtersOpen: false,
      hasActiveFilters: false,
      searchQuery: "",
      searchField,
      sortField: "title",
      sortDir: "asc",
      ...handlers,
      ...rest,
    },
  });
  return handlers;
}

describe("SidebarControls menus", () => {
  it("clears only the search text and returns focus to the search input", async () => {
    const { onSearchQueryChange, onSearchFieldChange } = renderControls({
      searchField: "studio",
      searchQuery: "A24",
    });

    await fireEvent.click(screen.getByRole("button", { name: "Clear search" }));

    expect(onSearchQueryChange).toHaveBeenCalledWith("");
    expect(onSearchFieldChange).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Search sidebar" })).toHaveFocus();
  });

  it("hides the clear button when the selected search field has no text", () => {
    renderControls({ searchField: "studio" });

    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  });

  it("opens the sort menu on its checked option and moves through options by keyboard", async () => {
    const { onSetSort } = renderControls({ sortField: "year", sortDir: "desc" });
    const button = screen.getByRole("button", { name: "Choose sort order" });

    await fireEvent.click(button);
    const menu = screen.getByRole("menu", { name: "Sort by" });
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("menuitemradio", { name: /Year/ })).toHaveFocus();
    expect(screen.getByRole("menuitemradio", { name: /Year/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    await fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitemradio", { name: "Date added" })).toHaveFocus();
    await fireEvent.keyDown(menu, { key: "End" });
    expect(screen.getByRole("menuitemradio", { name: "Theme length" })).toHaveFocus();
    await fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(screen.getByRole("menuitemradio", { name: "Title" })).toHaveFocus();

    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Last matched" }));
    expect(onSetSort).toHaveBeenCalledWith("last_matched_at", "desc");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("closes a menu with Escape and returns focus to its button", async () => {
    renderControls();
    const button = screen.getByRole("button", { name: "Choose search field" });

    await fireEvent.keyDown(button, { key: "ArrowDown" });
    const menu = screen.getByRole("menu", { name: "Search by" });
    expect(screen.getByRole("menuitemradio", { name: "Title" })).toHaveFocus();

    await fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("offers ID and YouTube search on both tabs and director search on movies only", async () => {
    renderControls({ tab: "show", searchField: "youtube" });

    expect(screen.getByRole("textbox", { name: "Search sidebar" })).toHaveAttribute(
      "placeholder",
      "Search YouTube...",
    );
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));
    expect(
      screen.getAllByRole("menuitemradio").map((option) => option.textContent?.trim()),
    ).toEqual(["Title", "Studio", "Year", "TMDB, TVDB or IMDb ID", "YouTube link, ID or title"]);
    // Without TMDB there is one group, so no headings or separator.
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.queryByText("Library")).toBeNull();
  });

  it("lists TMDB search apart from the library fields", async () => {
    renderControls({ tmdbConfigured: true });
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));

    const library = screen.getByRole("group", { name: "Library" });
    const tmdb = screen.getByRole("group", { name: "TMDB" });
    expect(screen.getByRole("separator")).toBeInTheDocument();
    expect(
      within(library).getByRole("menuitemradio", { name: "TMDB, TVDB or IMDb ID" }),
    ).toBeVisible();
    expect(
      within(tmdb)
        .getAllByRole("menuitemradio")
        .map((option) => option.textContent?.trim()),
    ).toEqual(["Title or ID"]);

    // Arrow keys move across both groups.
    const menu = screen.getByRole("menu", { name: "Search by" });
    within(library).getByRole("menuitemradio", { name: "YouTube link, ID or title" }).focus();
    await fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(within(tmdb).getByRole("menuitemradio", { name: "Title or ID" })).toHaveFocus();
  });

  it("hides the filters and sort while searching TMDB", () => {
    renderControls({ tmdbConfigured: true, searchField: "tmdb", hasActiveFilters: true });

    expect(screen.queryByRole("button", { name: "Open filters" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Choose sort order" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Search sidebar" })).toHaveAttribute(
      "placeholder",
      "Search TMDB by title or ID...",
    );
  });

  it("marks a chosen search field by colour only, leaving the hint to name it", () => {
    renderControls({ searchField: "studio" });

    const button = screen.getByRole("button", { name: "Choose search field" });
    expect(button).toHaveClass("active");
    expect(button).toHaveTextContent("");
    expect(screen.getByRole("textbox", { name: "Search sidebar" })).toHaveAttribute(
      "placeholder",
      "Search studios...",
    );
  });

  it("searches and sorts collections by their own fields", async () => {
    const { onSetSort } = renderControls({ mode: "collections" });

    expect(screen.getByRole("textbox", { name: "Search sidebar" })).toHaveAttribute(
      "placeholder",
      "Search 3 collections...",
    );
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));
    expect(
      screen.getAllByRole("menuitemradio").map((option) => option.textContent?.trim()),
    ).toEqual(["Title or TMDB collection ID", "Group", "YouTube link, ID or title"]);
    await fireEvent.keyDown(screen.getByRole("menu", { name: "Search by" }), { key: "Escape" });
    await fireEvent.click(screen.getByRole("button", { name: "Choose sort order" }));
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Number of items" }));
    expect(onSetSort).toHaveBeenCalledWith("child_count", "desc");
  });

  it("focuses the search input on / or Ctrl+K shortcut", async () => {
    renderControls();
    const input = screen.getByRole("textbox", { name: "Search sidebar" });

    await fireEvent.keyDown(window, { key: "/" });
    expect(input).toHaveFocus();

    input.blur();
    expect(input).not.toHaveFocus();

    await fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(input).toHaveFocus();
  });
});
