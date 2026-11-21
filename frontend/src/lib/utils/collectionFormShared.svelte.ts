import { SvelteMap, SvelteSet } from "svelte/reactivity";
import { UNGROUPED_GROUP } from "../../generated/settings";
import type {
  ArtStyle,
  AutoArtSource,
  CollectionDimensionRead,
  CollectionFiltering,
  CollectionGeneratorInput,
  CollectionGroupPolicyInput,
  CollectionMode,
  CollectionOptions,
  CollectionOrder,
  CollectionPosterStyle,
  CollectionRuleWriteInput,
  FilterGroupInput,
  MediaType,
  SyncMode,
} from "../../generated/rest/types.gen";
import { availableFields, availableOrders, emptyGroup } from "./collectionCriteria";
import type { CollectionOptions as Capabilities } from "./libraries.svelte";

/** Collection policy as a collection, a group and the global defaults hold it. */
export type PolicyData = {
  sync_mode?: SyncMode | null;
  minimum_items?: number | null;
  delete_below_minimum?: boolean | null;
  auto_art?: AutoArtSource[] | null;
  generated_style?: ArtStyle | null;
  generated_title_only?: boolean | null;
  overturedb_posters?: CollectionPosterStyle[] | null;
  backgrounds?: boolean | null;
  themes?: boolean | null;
  auto_match_theme?: boolean | null;
  request_missing?: boolean | null;
  member_label?: string | null;
  arr_tag?: string | null;
  collection_filtering?: CollectionFiltering | null;
  collection_mode?: CollectionMode | null;
  order_type?: CollectionOrder | null;
  visible_home?: boolean | null;
  visible_shared?: boolean | null;
  visible_library?: boolean | null;
  home_order?: number | null;
  sort_title_format?: string | null;
  summary_format?: string | null;
};

/** When collections are active each year, at any level; syncs follow Sync schedules. */
export type ScheduleData = {
  active_start_mmdd?: string | null;
  active_end_mmdd?: string | null;
  delete_when_inactive?: boolean | null;
};

/** What a new collection form creates. */
export type DraftKind = "collection" | "set";

/** A set's generator, whose criteria the form always edits in place. */
export type SetGenerator = CollectionGeneratorInput & { criteria: FilterGroupInput };
/** The defaults a set's group gives its collections. */
export type SetPolicy = Omit<CollectionGroupPolicyInput, "generator">;

/** Fields and helpers shared between mounted collection editors and unsaved drafts. */
export interface CollectionFormLike {
  readonly mediaTypes: MediaType[];
  readonly options: Capabilities;
  readonly capabilities: ReturnType<Capabilities["for"]>;
  readonly lastCriteria: SvelteMap<MediaType, FilterGroupInput>;
  readonly orders: CollectionOrder[];
  rule: CollectionRuleWriteInput;
  title: string;
  sortTitleFormat: string;
  summaryFormat: string;
  activeStartMmdd: string;
  activeEndMmdd: string;
  deleteWhenInactive: boolean | null;
  collectionFiltering: CollectionFiltering | null;
  collectionMode: CollectionMode | null;
  orderType: CollectionOrder | null;
  visibleHome: boolean | null;
  visibleShared: boolean | null;
  visibleLibrary: boolean | null;
  collectionGroup: string;
  tmdbCollectionId: number | undefined;
  typeOf(libraryId: string): MediaType;
}

/** Make the criteria Plex's live filter or Overture's, dropping an order the new kind cannot keep. */
export function switchKind(form: CollectionFormLike, smart: boolean) {
  form.rule.smart = smart;
  dropUnofferedOrder(form);
}

/** Clears a chosen order the form no longer offers. */
function dropUnofferedOrder(form: CollectionFormLike) {
  if (form.orderType !== null && !form.orders.includes(form.orderType)) form.orderType = null;
}

/** What a collection form derives from its rule and the libraries it names. */
export abstract class CollectionRuleForm {
  abstract rule: CollectionRuleWriteInput;
  abstract readonly options: Capabilities;
  abstract typeOf(libraryId: string): MediaType;

  get smart() {
    return !!this.rule.smart;
  }
  get libraryIds() {
    return this.rule.libraries.map((entry) => entry.library_id);
  }
  /** What the chosen libraries hold, movies first. */
  get mediaTypes(): MediaType[] {
    return heldTypes(this.libraryIds, (id) => this.typeOf(id));
  }
  get capabilities() {
    return this.options.for(this.mediaTypes[0] ?? "movie");
  }
  /** What takes requests and tags for the chosen libraries. */
  get arr() {
    const names = { movie: "Radarr", show: "Sonarr" } as const;
    const usable = this.mediaTypes.filter((mediaType) => this.options.for(mediaType).data?.arr);
    return usable.map((mediaType) => names[mediaType]).join(" and ") || null;
  }
  fieldsFor(libraryId: string) {
    return availableFields(this.options.forLibrary(libraryId, this.typeOf(libraryId)), this.smart);
  }
  get orders() {
    return availableOrders(this.options.shared(this.mediaTypes), this.smart);
  }
}

export function defaultRule(): CollectionRuleWriteInput {
  return {
    libraries: [],
    smart: false,
    limit: null,
    sync_mode: null,
    minimum_items: null,
    delete_below_minimum: null,
    auto_art: null,
    generated_style: null,
    generated_title_only: null,
    overturedb_posters: null,
    backgrounds: null,
    themes: null,
    auto_match_theme: null,
    collection_mode: null,
    collection_filtering: null,
    visible_home: null,
    visible_shared: null,
    visible_library: null,
    order_type: null,
    sort_title_format: null,
    summary_format: null,
    active_start_mmdd: null,
    active_end_mmdd: null,
    delete_when_inactive: null,
    request_missing: null,
    member_label: null,
    arr_tag: null,
    home_order: null,
  };
}

/**
 * A generator split by *dimension*, starting with what the dimension starts sets with.
 * Only Plex can count a smart-only dimension, so it makes the set smart; leaving one
 * for a dimension Overture counts returns the set to Overture's evaluation.
 */
export function withDimension(
  generator: SetGenerator,
  dimension: CollectionDimensionRead,
  previous: CollectionDimensionRead | undefined,
): SetGenerator {
  return {
    ...generator,
    dimension: dimension.dimension,
    title_format: dimension.title_format,
    strip_prefix: dimension.strip_prefix,
    strip_suffix: dimension.strip_suffix,
    smart: dimension.smart_only || (!!generator.smart && !previous?.smart_only),
    custom_values:
      dimension.dimension === "custom"
        ? generator.custom_values?.length
          ? generator.custom_values
          : [{ name: "", criteria: emptyGroup() }]
        : [],
  };
}

export function defaultGenerator(libraryIds: string[] = []): SetGenerator {
  return {
    dimension: "decade",
    library_ids: libraryIds,
    include: [],
    exclude: [],
    top: null,
    title_format: "{value}s",
    strip_prefix: "",
    strip_suffix: "",
    criteria: emptyGroup(),
    smart: false,
    custom_values: [],
    aliases: [],
  };
}

/** Radarr, Sonarr or both, as far as the form's libraries can use them. */
function heldTypes(libraryIds: string[], typeOf: (id: string) => MediaType): MediaType[] {
  const held = new SvelteSet(libraryIds.map(typeOf));
  return (["movie", "show"] as const).filter((mediaType) => held.has(mediaType));
}

/** The rule a form saves; display choices are the rule's overrides. */
export function ruleBody(form: CollectionFormLike): CollectionRuleWriteInput {
  return {
    ...$state.snapshot(form.rule),
    sort_title_format: null,
    summary_format: null,
    collection_mode: form.collectionMode,
    collection_filtering: form.collectionFiltering,
    order_type: form.orderType,
    visible_home: form.visibleHome,
    visible_shared: form.visibleShared,
    visible_library: form.visibleLibrary,
  };
}

export function optionsBody(form: CollectionFormLike): CollectionOptions {
  return {
    title: form.title.trim(),
    summary: null,
    sort_title: null,
    sort_title_format: form.sortTitleFormat || null,
    summary_format: form.summaryFormat || null,
    active_start_mmdd: form.activeStartMmdd || null,
    active_end_mmdd: form.activeEndMmdd || null,
    delete_when_inactive: form.deleteWhenInactive,
    collection_filtering: form.collectionFiltering,
    collection_group: form.collectionGroup || UNGROUPED_GROUP,
    tmdb_collection_id: form.tmdbCollectionId ?? null,
    collection_mode: form.collectionMode,
    ...(form.orderType === null ? {} : { order_type: form.orderType }),
    ...(form.visibleHome === null ? {} : { visible_home: form.visibleHome }),
    ...(form.visibleShared === null ? {} : { visible_shared: form.visibleShared }),
    ...(form.visibleLibrary === null ? {} : { visible_library: form.visibleLibrary }),
  };
}

/** The criteria a library starts with: another of its kind's, the last one's, or none. */
function startingCriteria(
  form: CollectionFormLike,
  mediaType: MediaType,
  fallback: FilterGroupInput,
): FilterGroupInput {
  const alike = form.rule.libraries.find((entry) => form.typeOf(entry.library_id) === mediaType);
  return alike
    ? structuredClone($state.snapshot(alike.criteria))
    : (form.lastCriteria.get(mediaType) ?? fallback);
}

/** Add a library to the form's rule, or take it out. */
export function setLibrary(
  form: CollectionFormLike,
  libraryId: string,
  chosen: boolean,
  fallback: FilterGroupInput,
) {
  const leaving = form.rule.libraries.find((entry) => entry.library_id === libraryId);
  if (leaving)
    form.lastCriteria.set(
      form.typeOf(libraryId),
      $state.snapshot(leaving.criteria) as FilterGroupInput,
    );
  form.rule.libraries = chosen
    ? [
        ...form.rule.libraries,
        {
          library_id: libraryId,
          criteria: startingCriteria(form, form.typeOf(libraryId), fallback),
        },
      ]
    : form.rule.libraries.filter((entry) => entry.library_id !== libraryId);
  dropUnofferedOrder(form);
}

/** The rule settings a collection keeps; Default leaves them null. */
const RULE_POLICY = [
  "sync_mode",
  "minimum_items",
  "delete_below_minimum",
  "auto_art",
  "generated_style",
  "generated_title_only",
  "overturedb_posters",
  "backgrounds",
  "themes",
  "auto_match_theme",
  "request_missing",
  "member_label",
  "arr_tag",
  "home_order",
] as const satisfies readonly (keyof CollectionRuleWriteInput)[];
type RulePolicy = Pick<CollectionRuleWriteInput, (typeof RULE_POLICY)[number]>;

/**
 * A form's settings as the settings fields edit them at every level. Display
 * choices belong to the collection as well as its rule, so they live on the
 * form; the rest are the rule's.
 */
export function formPolicy(form: CollectionFormLike) {
  const rule: RulePolicy = {};
  for (const key of RULE_POLICY) {
    Object.defineProperty(rule, key, {
      enumerable: true,
      get: () => form.rule[key],
      set: (value: RulePolicy[typeof key]) => {
        Object.assign(form.rule, { [key]: value ?? null });
      },
    });
  }
  return Object.defineProperties(rule, {
    order_type: {
      get: () => form.orderType,
      set: (value: CollectionOrder | null | undefined) => (form.orderType = value ?? null),
    },
    collection_mode: {
      get: () => form.collectionMode,
      set: (value: CollectionMode | null | undefined) => (form.collectionMode = value ?? null),
    },
    collection_filtering: {
      get: () => form.collectionFiltering,
      set: (value: CollectionFiltering | null | undefined) =>
        (form.collectionFiltering = value ?? null),
    },
    visible_home: {
      get: () => form.visibleHome,
      set: (value: boolean | null | undefined) => (form.visibleHome = value ?? null),
    },
    visible_shared: {
      get: () => form.visibleShared,
      set: (value: boolean | null | undefined) => (form.visibleShared = value ?? null),
    },
    visible_library: {
      get: () => form.visibleLibrary,
      set: (value: boolean | null | undefined) => (form.visibleLibrary = value ?? null),
    },
    sort_title_format: {
      get: () => form.sortTitleFormat || null,
      set: (value: string | null | undefined) => (form.sortTitleFormat = value ?? ""),
    },
    summary_format: {
      get: () => form.summaryFormat || null,
      set: (value: string | null | undefined) => (form.summaryFormat = value ?? ""),
    },
    active_start_mmdd: {
      get: () => form.activeStartMmdd || null,
      set: (value: string | null | undefined) => (form.activeStartMmdd = value ?? ""),
    },
    active_end_mmdd: {
      get: () => form.activeEndMmdd || null,
      set: (value: string | null | undefined) => (form.activeEndMmdd = value ?? ""),
    },
    delete_when_inactive: {
      get: () => form.deleteWhenInactive,
      set: (value: boolean | null | undefined) => (form.deleteWhenInactive = value ?? null),
    },
    // Object.defineProperties types only its target, not the accessors it adds.
  }) as RulePolicy & PolicyData & ScheduleData;
}
