import { fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SourceOrderList from "../../../lib/components/SourceOrderList.svelte";

const labels = { tmdb: "TMDB", fanart: "Fanart.tv", overturedb: "OvertureDB" };

function renderList(overrides: { disabledSources?: string[] } = {}) {
  const ontoggle = vi.fn();
  const onmove = vi.fn();
  render(SourceOrderList, {
    sourceOrder: ["tmdb", "fanart", "overturedb"],
    selectedSources: ["tmdb", "overturedb"],
    labels,
    storageKey: "art",
    ontoggle,
    onmove,
    ...overrides,
  });
  return { ontoggle, onmove };
}

const row = (label: string) => screen.getByText(label).closest<HTMLElement>("[role=listitem]")!;
const handle = (label: string) => row(label).querySelector<HTMLButtonElement>("button")!;

/** Lay the rows out 40px apart, as the browser would. */
function layOutRows() {
  screen.getAllByRole("listitem").forEach((element, index) => {
    element.getBoundingClientRect = () => DOMRect.fromRect({ y: index * 40, height: 40 });
  });
}

describe("SourceOrderList", () => {
  beforeEach(() => {
    // jsdom has no pointer capture; a drag only needs the call to succeed.
    HTMLElement.prototype.setPointerCapture = () => {};
  });

  afterEach(() => {
    delete (HTMLElement.prototype as Partial<HTMLElement>).setPointerCapture;
  });

  it("lists the sources in order with their selection", async () => {
    const { ontoggle } = renderList();

    expect(screen.getAllByRole("listitem").map((item) => item.textContent?.trim())).toEqual([
      "TMDB",
      "Fanart.tv",
      "OvertureDB",
    ]);
    expect(screen.getByRole("checkbox", { name: "TMDB" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Fanart.tv" })).not.toBeChecked();

    await fireEvent.click(screen.getByRole("checkbox", { name: "Fanart.tv" }));
    expect(ontoggle).toHaveBeenCalledWith("fanart");
  });

  it("keeps catalog sources off and fixed while OvertureDB is disabled", async () => {
    const { onmove } = renderList({ disabledSources: ["overturedb"] });

    const checkbox = screen.getByRole("checkbox", { name: /OvertureDB/ });
    expect(checkbox).toBeDisabled();
    expect(checkbox).not.toBeChecked();
    expect(row("OvertureDB")).toHaveTextContent("enable OvertureDB first");
    expect(handle("OvertureDB")).toBeDisabled();

    await fireEvent.drop(row("TMDB"), { dataTransfer: { getData: () => "overturedb" } });
    expect(onmove).not.toHaveBeenCalled();
  });

  it("moves a source dropped onto another", async () => {
    const { onmove } = renderList();
    const dataTransfer = { setData: vi.fn(), getData: () => "", effectAllowed: "" };

    await fireEvent.dragStart(row("OvertureDB"), { dataTransfer });
    await fireEvent.drop(row("TMDB"), { dataTransfer });

    expect(dataTransfer.setData).toHaveBeenCalledWith("text/plain", "overturedb");
    expect(onmove).toHaveBeenCalledWith("overturedb", "tmdb");
  });

  it("moves a source dragged by its handle once the pointer has really moved", async () => {
    const { onmove } = renderList();
    layOutRows();
    const grip = handle("OvertureDB");

    await fireEvent.pointerDown(grip, { button: 0, pointerId: 1, clientY: 100 });
    await fireEvent.pointerMove(grip, { pointerId: 1, clientY: 95 });
    expect(onmove).not.toHaveBeenCalled();

    await fireEvent.pointerMove(grip, { pointerId: 1, clientY: 10 });
    expect(onmove).toHaveBeenCalledWith("overturedb", "tmdb");

    await fireEvent.pointerUp(grip, { pointerId: 1 });
    await fireEvent.pointerMove(grip, { pointerId: 1, clientY: 50 });
    expect(onmove).toHaveBeenCalledOnce();
  });

  it("ignores pointers other than the primary button", async () => {
    const { onmove } = renderList();
    layOutRows();
    const grip = handle("OvertureDB");

    await fireEvent.pointerDown(grip, { button: 2, pointerId: 1, clientY: 100 });
    await fireEvent.pointerMove(grip, { pointerId: 1, clientY: 10 });

    expect(onmove).not.toHaveBeenCalled();
  });
});
