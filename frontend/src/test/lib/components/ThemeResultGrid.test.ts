import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import ThemeResultGrid from "../../../lib/components/ThemeResultGrid.svelte";
import { themeSearchResult } from "../../helpers/fixtures";

const results = [
  themeSearchResult({
    id: "abc123_DEF0",
    title: "Main Theme",
    channel: "OST Channel",
    duration: 65,
  }),
  themeSearchResult({
    id: "xyz987_GHI1",
    title: "Alternate Theme",
    duration: 125,
  }),
];

describe("ThemeResultGrid", () => {
  it("renders shared YouTube result cards with normalized metadata", () => {
    render(ThemeResultGrid, {
      props: {
        results,
        currentYoutubeId: "abc123_DEF0",
        onSelect: vi.fn(),
      },
    });

    expect(screen.getByText("Main Theme")).toBeInTheDocument();
    expect(screen.getByText("OST Channel")).toBeInTheDocument();
    expect(screen.getByText("1:05")).toBeInTheDocument();
    expect(screen.getByTitle("Main Theme")).toHaveAttribute(
      "src",
      "https://www.youtube-nocookie.com/embed/abc123_DEF0",
    );
    expect(screen.getByRole("button", { name: "Overwrite" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Select" })).toBeInTheDocument();
  });

  it("uses caller labels and forwards selected videos", async () => {
    const onSelect = vi.fn();
    render(ThemeResultGrid, {
      props: {
        results,
        currentYoutubeId: "abc123_DEF0",
        selectLabel: (video) => (video.id === "abc123_DEF0" ? "Assigned" : "Queue"),
        onSelect,
      },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Queue" }));

    expect(screen.getByRole("button", { name: "Assigned" })).toBeInTheDocument();
    expect(onSelect).toHaveBeenCalledWith(results[1]);
  });

  it("renders source badges with respective visual styles", () => {
    const badgedResults = [
      {
        ...results[0]!,
        badges: [
          { label: "Currently Selected", variant: "success" },
          { label: "OvertureDB", variant: "accent" },
        ],
      },
      {
        ...results[1]!,
        badges: [{ label: "ThemerrDB", variant: "warning" }],
      },
    ];

    render(ThemeResultGrid, {
      props: {
        results: badgedResults,
        onSelect: vi.fn(),
      },
    });

    const selectedBadge = screen.getByText("Currently Selected");
    expect(selectedBadge).toBeInTheDocument();
    expect(selectedBadge).toHaveClass("badge", "badge-success");

    const overtureBadge = screen.getByText("OvertureDB");
    expect(overtureBadge).toBeInTheDocument();
    expect(overtureBadge).toHaveClass("badge", "badge-accent");

    const themerrBadge = screen.getByText("ThemerrDB");
    expect(themerrBadge).toBeInTheDocument();
    expect(themerrBadge).toHaveClass("badge", "badge-warning");
  });
});
