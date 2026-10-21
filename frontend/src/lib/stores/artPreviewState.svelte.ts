import { SvelteMap } from "svelte/reactivity";
import type { MediaItemRead } from "../../generated/rest/types.gen";
import { itemArtDisplayUrl } from "../utils/artDisplay";

type DetailArtType = "poster" | "background";

type ArtPreview = {
  /** The chosen candidate as the art grid showed it, so already loaded. */
  previewUrl: string;
  /** The item's art when the choice was saved: the preview stands in only for it. */
  replacing: string | null;
  jobId: string | null;
};

const ART_TYPES: readonly DetailArtType[] = ["poster", "background"];

function previewKey(itemId: number, artType: DetailArtType) {
  return `${itemId}:${artType}`;
}

/**
 * Chosen artwork shown on the detail page while the server fetches the file.
 *
 * A preview replaces only the art the item showed when the choice was saved.
 * It goes as soon as the item shows other art (the new file), or when the
 * download fails, is cancelled or finds the file already in place.
 */
class ArtPreviewState {
  private previews = new SvelteMap<string, ArtPreview>();

  show(item: MediaItemRead, artType: DetailArtType, previewUrl: string, jobId: string | null) {
    this.previews.set(previewKey(item.id, artType), {
      previewUrl,
      replacing: itemArtDisplayUrl(item, artType),
      jobId,
    });
  }

  /** The preview to show for the item's art, or null to show the item's own. */
  previewFor(item: MediaItemRead, artType: DetailArtType): string | null {
    const preview = this.previews.get(previewKey(item.id, artType));
    if (!preview || preview.replacing !== itemArtDisplayUrl(item, artType)) {
      return null;
    }
    return preview.previewUrl;
  }

  /** Fresh item data: a preview whose art has been replaced has done its job. */
  itemUpdated(item: MediaItemRead) {
    for (const artType of ART_TYPES) {
      const key = previewKey(item.id, artType);
      const preview = this.previews.get(key);
      if (preview && preview.replacing !== itemArtDisplayUrl(item, artType)) {
        this.previews.delete(key);
      }
    }
  }

  /** A download ended without new art: the item keeps showing what it had. */
  jobEnded(jobId: string) {
    for (const [key, preview] of this.previews) {
      if (preview.jobId === jobId) this.previews.delete(key);
    }
  }

  clear(itemId: number, artType: DetailArtType) {
    this.previews.delete(previewKey(itemId, artType));
  }

  /** After a reconnect the refetched items are the truth, whatever happened meanwhile. */
  reset() {
    this.previews.clear();
  }
}

export const artPreviewState = new ArtPreviewState();
