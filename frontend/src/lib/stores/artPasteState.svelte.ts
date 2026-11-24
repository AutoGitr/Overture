/**
 * What the art slot on screen offers the header's paste and upload buttons,
 * published by the slot while it is shown.
 */
export type ArtPasteTarget = {
  /** Slot name for the button label, e.g. "poster" or "season poster". */
  readonly label: string;
  readonly busy: boolean;
  paste: () => Promise<void>;
  /** Saves an image file into the slot; null where only public links are stored. */
  readonly upload: ((file: File) => Promise<void>) | null;
};

class ArtPasteState {
  // Raw: the slot replaces the whole value; its functions need no proxy.
  target = $state.raw<ArtPasteTarget | null>(null);
}

export const artPasteState = new ArtPasteState();
