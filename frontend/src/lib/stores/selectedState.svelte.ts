import type { ArtType, MediaItemRead, TmdbItemPreview } from "../../generated/rest/types.gen";
import { settingsState } from "./settingsState.svelte";

/** What the detail view shows: a stored item, or a TMDB title not yet stored. */
export type DetailSubject = MediaItemRead | TmdbItemPreview;

class SelectedState {
  private itemId = $state<number | null>(null);

  item = $state<MediaItemRead | null>(null);
  /** A TMDB title open before its first selection stores it as an item. */
  preview = $state<TmdbItemPreview | null>(null);

  mode = $state<"art" | "themes" | "database" | "monitor">("art");
  artSubTab = $state<"poster" | "background" | "seasons">("poster");

  drillSeasonNum = $state<number | null>(null);

  get selectedItemId(): number | null {
    return this.itemId;
  }

  get subject(): DetailSubject | null {
    return this.item ?? this.preview;
  }

  private resetView() {
    this.drillSeasonNum = null;
    this.mode = settingsState.initial_tab;
    this.artSubTab = "poster";
  }

  selectItem(item: MediaItemRead | null) {
    this.itemId = item?.id ?? null;
    this.item = item;
    this.preview = null;
    this.resetView();
  }

  selectPreview(preview: TmdbItemPreview) {
    this.itemId = null;
    this.item = null;
    this.preview = preview;
    this.resetView();
  }

  updateItemData(item: MediaItemRead) {
    if (this.itemId === item.id) this.item = item;
  }

  get isShow(): boolean {
    return this.subject?.media_type === "show";
  }

  get currentArtType(): ArtType {
    return this.artSubTab === "seasons" ? "season_poster" : this.artSubTab;
  }
}

export const selectedState = new SelectedState();
