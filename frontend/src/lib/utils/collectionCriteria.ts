import type {
  CollectionCapabilities,
  CollectionFieldRead,
  CollectionOrder,
  CollectionSourceInput,
  ConditionInput,
  FieldConditionInput,
  FilterGroupInput,
  FilterOperator,
  SourceType,
} from "../../generated/rest/types.gen";

export const OPERATOR_LABELS: Record<FilterOperator, string> = {
  is: "is",
  is_not: "is not",
  contains: "contains",
  does_not_contain: "does not contain",
  starts_with: "starts with",
  ends_with: "ends with",
  gt: "is greater than",
  gte: "is at least",
  lt: "is less than",
  lte: "is at most",
  in_last: "in the last (days)",
  not_in_last: "not in the last (days)",
  before: "is before",
  after: "is after",
};

/** Source conditions read as membership, so their operators do too. */
export const SOURCE_OPERATOR_LABELS = { is: "in", is_not: "not in" } as const;

export const ORDER_LABELS: Record<CollectionOrder, string> = {
  custom: "Custom (manual or source order)",
  "release.asc": "Release date (oldest first)",
  "release.desc": "Release date (newest first)",
  "title.asc": "Title (A to Z)",
  "title.desc": "Title (Z to A)",
  "added.desc": "Date added (newest first)",
  "added.asc": "Date added (oldest first)",
  "critic_rating.desc": "Critic rating (highest first)",
  "critic_rating.asc": "Critic rating (lowest first)",
  "audience_rating.desc": "Audience rating (highest first)",
  "audience_rating.asc": "Audience rating (lowest first)",
  "user_rating.desc": "User rating (highest first)",
  "user_rating.asc": "User rating (lowest first)",
  "duration.desc": "Duration (longest first)",
  "duration.asc": "Duration (shortest first)",
  "plays.desc": "Plays (most first)",
  "plays.asc": "Plays (fewest first)",
  "last_played.desc": "Last played (most recent first)",
  "last_played.asc": "Last played (least recent first)",
  random: "Random",
};

export function emptyGroup(mode: FilterGroupInput["mode"] = "all"): FilterGroupInput {
  return { mode, conditions: [], groups: [] };
}

export function groupIsEmpty(group: FilterGroupInput): boolean {
  return !group.conditions?.length && (group.groups ?? []).every(groupIsEmpty);
}

/** The fields a collection can test, as Overture or as Plex evaluates it. */
export function availableFields(
  capabilities: CollectionCapabilities | undefined,
  smart: boolean,
): CollectionFieldRead[] {
  return (capabilities?.fields ?? []).filter((field) => (smart ? field.smart : field.local));
}

export function availableOrders(
  capabilities: CollectionCapabilities | undefined,
  smart: boolean,
): CollectionOrder[] {
  return (smart ? capabilities?.smart_orders : capabilities?.orders) ?? [];
}

export function defaultValue(
  field: CollectionFieldRead,
  operator: FilterOperator,
): FieldConditionInput["value"] {
  if (field.kind === "boolean") return true;
  if (field.kind === "number" || operator === "in_last" || operator === "not_in_last") return 30;
  if (operator === "before" || operator === "after") return new Date().toISOString().slice(0, 10);
  return "";
}

export function fieldCondition(field: CollectionFieldRead): ConditionInput {
  const operator = field.operators[0] ?? "is";
  return { kind: "field", field: field.field, operator, value: defaultValue(field, operator) };
}

export function newSource(type: SourceType): CollectionSourceInput {
  switch (type) {
    case "tmdb_collection":
      return { type, collection_id: 0 };
    case "tmdb_list":
      return { type, list_ids: [] };
    case "tmdb_item":
      return { type, tmdb_ids: [] };
    case "tmdb_person":
      return { type, person_id: 0, roles: ["actor"], use_biography: false };
    case "mdblist":
      return { type, identifiers: [] };
    case "radarr_tag":
    case "sonarr_tag":
      return { type, tags: [] };
  }
}

export function sourceCondition(type: SourceType): ConditionInput {
  return { kind: "source", operator: "is", source: newSource(type) };
}

/** Criteria a TMDB franchise seeds: the franchise's movies. */
export function franchiseCriteria(collectionId: number): FilterGroupInput {
  return {
    mode: "all",
    conditions: [
      {
        kind: "source",
        operator: "is",
        source: { type: "tmdb_collection", collection_id: collectionId },
      },
    ],
    groups: [],
  };
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
