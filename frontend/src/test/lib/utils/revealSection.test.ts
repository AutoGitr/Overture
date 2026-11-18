import { afterEach, describe, expect, it, vi } from "vitest";
import { revealSection } from "../../../lib/utils/revealSection";

function part(id: string, expanded: boolean) {
  const toggle = document.createElement("button");
  toggle.setAttribute("aria-controls", `${id}-body`);
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.addEventListener("click", () => toggle.setAttribute("aria-expanded", "true"));
  const body = document.createElement("div");
  body.id = `${id}-body`;
  return { toggle, body };
}

afterEach(() => document.body.replaceChildren());

describe("revealSection", () => {
  it("opens only the section's own collapsed parts and focuses it", async () => {
    const section = document.createElement("section");
    section.id = "form-settings";
    section.tabIndex = -1;
    const own = part("own", false);
    const nested = part("nested", false);
    own.body.append(nested.toggle, nested.body);
    section.append(own.toggle, own.body);
    const other = document.createElement("section");
    const elsewhere = part("elsewhere", false);
    other.append(elsewhere.toggle, elsewhere.body);
    document.body.append(other, section);
    const observe = vi.spyOn(ResizeObserver.prototype, "observe");

    await revealSection("form-settings");

    expect(own.toggle).toHaveAttribute("aria-expanded", "true");
    expect(nested.toggle).toHaveAttribute("aria-expanded", "false");
    expect(elsewhere.toggle).toHaveAttribute("aria-expanded", "false");
    expect(section).toHaveFocus();
    expect(observe).toHaveBeenCalledWith(section);
  });
});
