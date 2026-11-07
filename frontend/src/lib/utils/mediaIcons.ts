import Clapperboard from "@lucide/svelte/icons/clapperboard";
import GalleryVerticalEnd from "@lucide/svelte/icons/gallery-vertical-end";
import Layers from "@lucide/svelte/icons/layers";
import Tv from "@lucide/svelte/icons/tv";

/** The one icon for each kind of entry the app lists. */
export const MEDIA_ICONS = {
  movie: Clapperboard,
  show: Tv,
  season: GalleryVerticalEnd,
  collection: Layers,
} as const;

export type MediaIcon = (typeof MEDIA_ICONS)[keyof typeof MEDIA_ICONS];
