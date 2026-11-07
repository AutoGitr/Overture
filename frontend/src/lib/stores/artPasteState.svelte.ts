/** The art slot currently on screen, so header controls can save into it. */
export type ArtPasteTarget = {
  /** Slot name for the button label, e.g. "poster" or "season poster". */
  readonly label: string;
  readonly busy: boolean;
  paste: () => Promise<void>;
  /** Saves an image file into the slot; null where only public links are stored. */
  readonly upload: ((file: File) => Promise<void>) | null;
};

class ArtPasteState {
  // Raw: the slot exposes live getters that must not be snapshotted by a proxy.
  target = $state.raw<ArtPasteTarget | null>(null);
}

export const artPasteState = new ArtPasteState();
