/**
 * Returns the trimmed http(s) link in pasted `text`, or null when it is not one.
 * Whether the link is usable artwork, and its canonical full-size form, is the
 * backend's to decide when the link is saved.
 */
export function parseArtUrl(text: string): string | null {
  const url = text.trim();
  try {
    const { protocol } = new URL(url);
    return protocol === "http:" || protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}
