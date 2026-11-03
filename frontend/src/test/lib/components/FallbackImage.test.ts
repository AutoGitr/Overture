import { fireEvent, render } from "@testing-library/svelte";
import { createRawSnippet, tick } from "svelte";
import { describe, expect, it, vi } from "vitest";
import FallbackImage from "../../../lib/components/FallbackImage.svelte";

const placeholder = createRawSnippet(() => ({ render: () => "<span>placeholder</span>" }));

describe("FallbackImage", () => {
  it("delays a new source, but shows one that already loaded at once", async () => {
    vi.useFakeTimers();
    const props = { src: "/poster-a.jpg", loadDelayMs: 100, placeholder };

    const first = render(FallbackImage, { props });
    expect(first.container.querySelector("img")).toBeNull();
    vi.advanceTimersByTime(100);
    await tick();
    const image = first.container.querySelector("img");
    expect(image).toHaveAttribute("src", "/poster-a.jpg");
    expect(image).toHaveAttribute("decoding", "async");
    await fireEvent.load(image as HTMLImageElement);
    first.unmount();
    expect(image).toHaveAttribute("src", "/poster-a.jpg");

    // A row scrolled back into view: the browser already has the image.
    const again = render(FallbackImage, { props });
    expect(again.container.querySelector("img")).toHaveAttribute("src", "/poster-a.jpg");

    const other = render(FallbackImage, { props: { ...props, src: "/poster-b.jpg" } });
    expect(other.container.querySelector("img")).toBeNull();
    vi.advanceTimersByTime(100);
    await tick();
    const unfinished = other.container.querySelector("img");
    expect(unfinished).toHaveAttribute("src", "/poster-b.jpg");
    other.unmount();
    expect(unfinished).toHaveAttribute("src", "");
  });

  it("shows the placeholder only when there is no image, never while one is on its way", async () => {
    vi.useFakeTimers();
    const waiting = render(FallbackImage, {
      props: { src: "/poster-c.jpg", loadDelayMs: 100, placeholder },
    });
    expect(waiting.container).toHaveTextContent("");
    vi.advanceTimersByTime(100);
    await tick();
    const image = waiting.container.querySelector("img") as HTMLImageElement;
    expect(waiting.container).not.toHaveTextContent("placeholder");

    await fireEvent.error(image);
    expect(waiting.container.querySelector("img")).toBeNull();
    expect(waiting.container).toHaveTextContent("placeholder");

    const missing = render(FallbackImage, { props: { src: null, loadDelayMs: 100, placeholder } });
    expect(missing.container).toHaveTextContent("placeholder");
  });
});
