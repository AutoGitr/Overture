/**
 * Bring a page section into view: open its collapsed parts, scroll to its top
 * and move focus there, so a section link lands on it wherever it was.
 */
export function revealSection(id: string): void {
  const section = document.getElementById(id);
  if (!section) return;
  const toggles = [...section.querySelectorAll<HTMLButtonElement>("button[aria-controls]")];
  const bodies = new Set(toggles.map((toggle) => toggle.getAttribute("aria-controls")));
  for (const toggle of toggles) {
    if (toggle.getAttribute("aria-expanded") !== "false") continue;
    // Only the section's own parts: one inside another part's body stays as it is.
    let parent = toggle.parentElement;
    while (parent && parent !== section && !bodies.has(parent.id)) parent = parent.parentElement;
    if (parent === section) toggle.click();
  }
  // Opening grows the section downwards, so its top is already where it will stay.
  section.scrollIntoView({ block: "start" });
  section.focus({ preventScroll: true });
}
