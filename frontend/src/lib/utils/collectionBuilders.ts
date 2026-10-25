import type {
  CollectionBuilderInput,
  FilterGroupInput,
  MediaType,
  SmartCollectionConfigInput,
} from "../../generated/rest/types.gen";

type BuilderType = CollectionBuilderInput["type"];

/** What a builder row offers, in the order the Source select lists it. */
export const BUILDER_KINDS: readonly {
  type: BuilderType;
  label: string;
  media: MediaType | null;
  needs: "tmdb" | "mdblist" | "radarr" | "sonarr" | null;
}[] = [
  { type: "tmdb_collection", label: "TMDB franchise", media: "movie", needs: "tmdb" },
  { type: "tmdb_item", label: "TMDB titles", media: null, needs: "tmdb" },
  { type: "tmdb_person", label: "TMDB person", media: null, needs: "tmdb" },
  { type: "mdblist", label: "MDBList", media: null, needs: "mdblist" },
  { type: "radarr_tag", label: "Radarr tags", media: "movie", needs: "radarr" },
  { type: "sonarr_tag", label: "Sonarr tags", media: "show", needs: "sonarr" },
  { type: "library_filter", label: "Library filter", media: null, needs: null },
];

export function emptyFilterGroup(): FilterGroupInput {
  return { mode: "all", conditions: [], groups: [] };
}

export function emptySmartFilter(): SmartCollectionConfigInput {
  return { filter_group: emptyFilterGroup(), sort_by: "release.desc", limit: null };
}

export function newBuilder(type: BuilderType): CollectionBuilderInput {
  switch (type) {
    case "tmdb_collection":
      return { type, collection_id: 0 };
    case "tmdb_item":
      return { type, tmdb_ids: [] };
    case "tmdb_person":
      return { type, person_id: 0, roles: ["actor"], use_biography: false };
    case "mdblist":
      return { type, identifiers: [""] };
    case "radarr_tag":
    case "sonarr_tag":
      return { type, tags: [] };
    case "library_filter":
      return { type, filter_group: emptyFilterGroup() };
  }
}

/** Split free text on commas and line breaks into trimmed, non-empty parts. */
export function splitList(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function splitIds(text: string): number[] {
  return splitList(text)
    .map(Number)
    .filter((id) => Number.isInteger(id) && id > 0);
}
