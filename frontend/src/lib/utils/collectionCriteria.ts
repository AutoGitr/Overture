import { ORDER_LABELS } from "../../generated/settings";
import type {
  CollectionCapabilities,
  CollectionFieldRead,
  CollectionSourceRead,
  CollectionOrder,
  CollectionSourceOutput,
  ConditionOutput,
  FieldConditionOutput,
  FilterGroupOutput,
  FilterOperator,
  MediaType,
  SourceType,
} from "../../generated/rest/types.gen";

/** Sort orders alphabetically, keeping a field's two directions together and custom first. */
export function sortedOrders(orders: readonly CollectionOrder[]): CollectionOrder[] {
  return [...orders].sort(
    (a, b) =>
      Number(b === "custom") - Number(a === "custom") ||
      ORDER_LABELS[a].localeCompare(ORDER_LABELS[b]),
  );
}

export function emptyGroup(mode: FilterGroupOutput["mode"] = "all"): FilterGroupOutput {
  return { mode, conditions: [], groups: [] };
}

export function groupIsEmpty(group: FilterGroupOutput): boolean {
  return !group.conditions.length && group.groups.every(groupIsEmpty);
}

/**
 * The fields a collection can test, with the operators of Overture or of Plex.
 * A smart collection is smart only on Plex; elsewhere Overture evaluates it.
 */
export function availableFields(
  capabilities: CollectionCapabilities | undefined,
  smart: boolean,
): CollectionFieldRead[] {
  const plex = smart && !!capabilities?.smart;
  return (capabilities?.fields ?? [])
    .filter((field) => (plex ? field.smart : field.local))
    .map((field) => (plex ? { ...field, operators: field.smart_operators } : field));
}

export function availableOrders(
  capabilities: CollectionCapabilities | undefined,
  smart: boolean,
): CollectionOrder[] {
  return (smart ? capabilities?.smart_orders : capabilities?.orders) ?? [];
}

/** Whether *operator* compares with a calendar date rather than a number or text. */
export function isDateOperator(operator: FilterOperator | undefined): boolean {
  return operator === "before" || operator === "after";
}

export function defaultValue(
  field: CollectionFieldRead,
  operator: FilterOperator,
): FieldConditionOutput["value"] {
  if (field.kind === "boolean") return true;
  if (field.kind === "number" || operator === "in_last" || operator === "not_in_last") return 30;
  if (isDateOperator(operator)) return new Date().toISOString().slice(0, 10);
  return field.choices[0]?.value ?? "";
}

export function fieldCondition(field: CollectionFieldRead): ConditionOutput {
  const operator = field.operators[0] ?? "is";
  return { kind: "field", field: field.field, operator, value: defaultValue(field, operator) };
}

export function newSource(type: SourceType): CollectionSourceOutput {
  switch (type) {
    case "tmdb_collection":
      return { type, collection_id: 0 };
    case "tmdb_list":
      return { type, list_ids: [] };
    case "tmdb_item":
      return { type, tmdb_ids: [] };
    case "tmdb_person":
      return { type, person_id: 0, person_name: null, roles: ["actor"] };
    case "tmdb_chart":
      return { type, chart: "popular", limit: 100 };
    case "mdblist":
      return { type, identifiers: [] };
    case "radarr_tag":
    case "sonarr_tag":
      return { type, tags: [] };
  }
}

export function sourceCondition(type: SourceType): ConditionOutput {
  return { kind: "source", operator: "is", source: newSource(type) };
}

/** Criteria a TMDB franchise seeds: the franchise's movies. */
export function franchiseCriteria(collectionId: number): FilterGroupOutput {
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

/** A TMDB page's URL ends in its ID, alone or before a slug: `/list/8136-best`. */
const TMDB_URL_ID = /\/([1-9]\d*)(?:-[^/]*)?\/?(?:[?#].*)?$/;

/** TMDB IDs typed as numbers or TMDB page URLs, and the entries that are neither. */
export function parseIds(text: string): { ids: number[]; invalid: string[] } {
  const ids: number[] = [];
  const invalid: string[] = [];
  for (const part of splitList(text)) {
    const id = /^[1-9]\d*$/.test(part) ? Number(part) : Number(TMDB_URL_ID.exec(part)?.[1]);
    if (Number.isSafeInteger(id) && id > 0) ids.push(id);
    else invalid.push(part);
  }
  return { ids, invalid };
}

/** What one set of criteria can test. */
export type CriteriaTarget = {
  fields: CollectionFieldRead[];
  sources: CollectionSourceRead[];
  mediaType: MediaType;
};

/** Sources whose values name titles of one media type: a movie's TMDB ID is another show's. */
const TYPED_SOURCES: ReadonlySet<SourceType> = new Set(["tmdb_item", "tmdb_chart"]);

/**
 * Whether criteria offering *target* can hold a condition copied from criteria
 * of *from*: they test its field with its operator, or offer its source.
 */
export function conditionFits(
  condition: ConditionOutput,
  target: CriteriaTarget,
  from: MediaType,
): boolean {
  if (condition.kind === "field") {
    const field = target.fields.find((entry) => entry.field === condition.field);
    return !!field && field.operators.includes(condition.operator);
  }
  const type = condition.source.type;
  return (
    target.sources.some((entry) => entry.type === type && !entry.unavailable) &&
    (!TYPED_SOURCES.has(type) || target.mediaType === from)
  );
}

/** Whether every condition of a copied group, at any depth, fits *target*. */
export function groupFits(
  group: FilterGroupOutput,
  target: CriteriaTarget,
  from: MediaType,
): boolean {
  return (
    group.conditions.every((condition) => conditionFits(condition, target, from)) &&
    group.groups.every((nested) => groupFits(nested, target, from))
  );
}
