import type {
  ConditionInput,
  FilterGroupInput,
  MediaItemRead,
} from "../../generated/rest/types.gen";
import { LIBRARY_STATUS_FIELDS } from "../../generated/settings";

/**
 * A custom filter is collection criteria. The server tests its metadata and
 * source conditions against what sync stored; library status conditions, and
 * how conditions combine, are tested here against the live library list, so
 * a status filter follows every download and choice at once.
 */

export type LibraryStatusField = (typeof LIBRARY_STATUS_FIELDS)[number];
type StatusValue = string | number | boolean | readonly string[] | null;

const agreement =
  (slot: keyof NonNullable<MediaItemRead["catalog_selections"]>) =>
  (item: MediaItemRead): StatusValue => {
    const value = item.catalog_selections?.[slot];
    return value ? [value] : [];
  };
const one = (value: string | null): StatusValue => (value ? [value] : []);

/** Each library status field's value on a title. */
const STATUS_VALUES = {
  monitored: (item) => item.monitored,
  art_status: (item) => [item.art_status],
  poster_status: (item) => [item.assets.poster.status],
  background_status: (item) => [item.assets.background.status],
  season_posters_status: (item) => [item.season_posters_status],
  poster_source: (item) => one(item.assets.poster.source),
  background_source: (item) => one(item.assets.background.source),
  poster_width: (item) => item.assets.poster.width,
  background_width: (item) => item.assets.background.width,
  incorrect_aspect_ratio: (item) => item.has_incorrect_aspect_ratio,
  theme_status: (item) => [item.assets.theme.status],
  theme_source: (item) => one(item.assets.theme.youtube_id_source),
  theme_length: (item) => item.assets.theme.duration,
  metadata_issue: (item) => item.metadata_issues,
  overturedb_complete: (item) => item.catalog_complete,
  themerrdb_theme: (item) => item.catalog_themerrdb,
  overturedb_poster: agreement("poster"),
  overturedb_background: agreement("background"),
  overturedb_season_posters: agreement("season_posters"),
  overturedb_theme: agreement("theme"),
} satisfies Record<LibraryStatusField, (item: MediaItemRead) => StatusValue>;

const STATUS_FIELDS: ReadonlySet<string> = new Set(LIBRARY_STATUS_FIELDS);

type StatusCondition = Extract<ConditionInput, { kind: "field" }> & {
  field: LibraryStatusField;
};

function isStatusCondition(condition: ConditionInput): condition is StatusCondition {
  return condition.kind === "field" && STATUS_FIELDS.has(condition.field);
}

/** Whether a group holds no condition at all, however deeply nested. */
export function isEmptyCriteria(group: FilterGroupInput): boolean {
  return !group.conditions?.length && (group.groups ?? []).every(isEmptyCriteria);
}

/** The conditions the server tests, in the order their matches come back. */
export function serverConditions(group: FilterGroupInput): ConditionInput[] {
  return [
    ...(group.conditions ?? []).filter((condition) => !isStatusCondition(condition)),
    ...(group.groups ?? []).flatMap(serverConditions),
  ];
}

const fold = (value: unknown) => String(value).toLocaleLowerCase();

function matchesStatus(
  value: StatusValue,
  operator: ConditionInput["operator"],
  target: string | number | boolean,
): boolean {
  if (Array.isArray(value)) {
    const found = value.some((entry) => fold(entry) === fold(target));
    return operator === "is_not" ? !found : found;
  }
  if (typeof value === "boolean") return (value === target) === (operator !== "is_not");
  if (typeof value !== "number") return false;
  const number = Number(target);
  switch (operator) {
    case "is_not":
      return value !== number;
    case "gt":
      return value > number;
    case "gte":
      return value >= number;
    case "lt":
      return value < number;
    case "lte":
      return value <= number;
    default:
      return value === number;
  }
}

/**
 * A title's test against the criteria, given what the server matched for each
 * of {@link serverConditions}, in that order. Empty nested groups are left out,
 * as the server leaves them out.
 */
export function criteriaPredicate(
  group: FilterGroupInput,
  matches: readonly (readonly number[])[],
): (item: MediaItemRead) => boolean {
  const tested = serverConditions(group);
  const matched = new Map(tested.map((condition, index) => [condition, new Set(matches[index])]));
  const test = (item: MediaItemRead, current: FilterGroupInput): boolean => {
    const results = [
      ...(current.conditions ?? []).map((condition) =>
        isStatusCondition(condition)
          ? matchesStatus(STATUS_VALUES[condition.field](item), condition.operator, condition.value)
          : (matched.get(condition)?.has(item.id) ?? false),
      ),
      ...(current.groups ?? [])
        .filter((nested) => !isEmptyCriteria(nested))
        .map((nested) => test(item, nested)),
    ];
    return current.mode === "any" ? results.some(Boolean) : results.every(Boolean);
  };
  return (item) => test(item, group);
}
