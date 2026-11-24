<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionCapabilitiesOptions,
    listCollectionsOptions,
    listCollectionGroupsOptions,
    listItemsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    AssetRemoval,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionMode,
    CollectionOrder,
    BulkItemOperation,
    BulkItemOperationResult,
    CollectionRead,
    MediaItemRead,
  } from "../../generated/rest/types.gen";
  import { applyBulkItemOperation, bulkSetCollectionMonitoredInCache } from "../rest/cache";
  import { chooseAction, confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { sidebarGroup } from "../router/routes";
  import { runBulkCollections } from "../utils/bulkCollections";
  import { sortedOrders } from "../utils/collectionCriteria";
  import { askRemoval, removedMessage } from "../utils/assetRemoval";
  import { errorMessage } from "../utils/errors";
  import { ORDER_LABELS, TEXT_LIMITS, UNGROUPED_GROUP } from "../../generated/settings";
  import { CollectionMembers } from "../utils/collectionMembers.svelte";
  import { CustomFilterMatch } from "../utils/customFilterMatch.svelte";
  import DataStatus from "./DataStatus.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PopupSection from "./PopupSection.svelte";
  import Select from "./Select.svelte";
  import type { SelectOption } from "../utils/selectOptions";
  import { groupOptions } from "../utils/collectionGroups.svelte";
  import {
    filterSidebarCollections,
    filterSidebarItems,
  } from "../utils/sidebarDomain";
  import { inCollectionGroup } from "../utils/sidebarShared";
  import { type FilterState } from "../stores/filterState.svelte";

  /** A request the popup owns, so its other actions wait while one runs. */
  interface Request<TBody, TResult> {
    mutateAsync: (variables: { body: TBody }) => Promise<TResult>;
    isPending: boolean;
    variables: { body: TBody } | undefined;
  }

  /** Operations on everything the filters and search currently match. */
  let {
    filters,
    catalogEnabled,
    itemsRequest,
    collectionsRequest,
  }: {
    /** The filters being edited, not yet applied to the sidebar. */
    filters: FilterState;
    catalogEnabled: boolean;
    itemsRequest: Request<BulkItemOperation, BulkItemOperationResult>;
    collectionsRequest: Request<BulkCollectionOperation, BulkCollectionOperationResult>;
  } = $props();

  const itemsQuery = createQuery(() => ({
    ...listItemsOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "items",
  }));
  const collectionsQuery = createQuery(() => ({
    ...listCollectionsOptions(),
    enabled: uiState.sidebarMode === "collections",
  }));
  const capabilities = createQuery(() => ({
    ...getCollectionCapabilitiesOptions({ query: { media_type: uiState.sidebarTab } }),
    enabled: uiState.sidebarMode === "collections",
  }));
  const groupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions(),
    enabled: uiState.sidebarMode === "collections",
  }));

  const customFilter = new CustomFilterMatch(() =>
    uiState.sidebarMode === "items"
      ? { mediaType: uiState.sidebarTab, filterId: filters.customFilter }
      : null,
  );
  const filteredCollection = new CollectionMembers(() =>
    uiState.sidebarMode === "items" ? filters.collectionId : null,
  );
  let items: MediaItemRead[] = $derived(
    uiState.sidebarMode === "items"
      ? filterSidebarItems({
          items: itemsQuery.data?.items ?? [],
          filters,
          catalogEnabled,
          collectionMembers: filteredCollection.ids,
          customFilter: customFilter.predicate,
          searchQuery: uiState.searchQuery,
          searchField: uiState.searchField,
          sortField: "title",
          sortDir: "asc",
        })
      : [],
  );
  let matchedCollections: CollectionRead[] = $derived(
    uiState.sidebarMode === "collections"
      ? filterSidebarCollections({
          collections: collectionsQuery.data ?? [],
          filters,
          catalogEnabled,
          searchQuery: uiState.searchQuery,
          searchField: uiState.searchField,
          sortField: "title",
          sortDir: "asc",
        }).filter(
          (collection) => sidebarGroup() === null || inCollectionGroup(collection, sidebarGroup()),
        )
      : [],
  );
  // Only adoption applies to collections Overture does not manage; everything else skips them.
  let collections = $derived(matchedCollections.filter((collection) => collection.managed));
  let unmanagedCollections = $derived(
    matchedCollections.filter((collection) => !collection.managed),
  );
  let noun = $derived(
    uiState.sidebarMode === "items"
      ? uiState.sidebarTab === "movie"
        ? "movies"
        : "shows"
      : "collections",
  );
  /** Whether the matching records are loaded, so counts are real. */
  let resultsReady = $derived(
    uiState.sidebarMode === "collections" ? collectionsQuery.isSuccess : itemsQuery.isSuccess,
  );

  type ItemOperation = "artwork" | "themes" | "delete";

  const feedback = createNotifier();
  let busy = $derived(itemsRequest.isPending || collectionsRequest.isPending);
  let forItems = $derived(uiState.sidebarMode === "items");
  let records = $derived<{ monitored: boolean }[]>(forItems ? items : collections);
  let matchCount = $derived(records.length);
  let monitoredCount = $derived(records.filter((record) => record.monitored).length);
  let unmonitoredCount = $derived(matchCount - monitoredCount);

  /** What a running request is doing, from the request itself. */
  let running = $derived.by(() => {
    if (itemsRequest.isPending && itemsRequest.variables) {
      const { operation, item_ids } = itemsRequest.variables.body;
      return { operation, count: item_ids.length };
    }
    if (collectionsRequest.isPending && collectionsRequest.variables) {
      const { operation, monitored, collection_ids } = collectionsRequest.variables.body;
      return {
        operation:
          operation === "set_monitored" ? (monitored ? "monitor" : "unmonitor") : operation,
        count: collection_ids.length,
      };
    }
    return null;
  });

  /** What removing art or themes from the filtered records asks about, by operation. */
  const REMOVED = { artwork: "art", themes: "theme" } as const;

  async function runItemOperation(operation: ItemOperation) {
    if (busy || !resultsReady || !forItems) return;
    const ids = items.map((item) => item.id);
    if (ids.length === 0) return;
    const target = `${ids.length} filtered ${noun}`;
    feedback.clear();
    try {
      let removal: AssetRemoval | null = null;
      if (operation === "delete") {
        const confirmed = await confirmAction({
          title: `Delete ${target}?`,
          message:
            `Their saved records will be removed from Overture. Local files and ${settingsState.media_server_name}'s items are kept, so titles still there may return after a sync.`,
          confirmLabel: "Delete",
          destructive: true,
        });
        if (!confirmed) return;
      } else {
        removal = await askRemoval(
          { asset: REMOVED[operation], item_ids: ids },
          `the ${operation === "artwork" ? "art, season posters included," : "themes"} of ${target}`,
        );
        if (!removal) return;
      }
      const result = await itemsRequest.mutateAsync({
        body: { item_ids: ids, operation, ...(removal ? { removal } : {}) },
      });
      applyBulkItemOperation(result);
      const count = result.item_ids.length;
      feedback.success(
        removal
          ? removedMessage(
              `the ${operation === "artwork" ? "art" : "themes"} of ${count} ${noun}`,
              removal,
              true,
            )
          : `Deleted ${count} ${noun} from Overture.`,
      );
      for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
    } catch (err: unknown) {
      feedback.error(errorMessage(err, "Bulk operation failed"));
    }
  }

  async function setMonitored(monitored: boolean) {
    const count = monitored ? unmonitoredCount : monitoredCount;
    if (count === 0 || busy || !resultsReady) return;
    const actionWord = monitored ? "Monitor" : "Unmonitor";
    const confirmed = await confirmAction({
      title: `${actionWord} ${count} filtered ${noun}?`,
      message: monitored
        ? "Asset workflows will include them."
        : "Asset workflows will skip them unless unmonitored items are included.",
      confirmLabel: actionWord,
    });
    if (!confirmed) return;

    feedback.clear();
    try {
      if (forItems) {
        const ids = items.filter((item) => item.monitored !== monitored).map((item) => item.id);
        const result = await itemsRequest.mutateAsync({
          body: { item_ids: ids, operation: monitored ? "monitor" : "unmonitor" },
        });
        applyBulkItemOperation(result);
        feedback.success(
          `${monitored ? "Monitored" : "Unmonitored"} ${result.item_ids.length} ${noun}.`,
        );
      } else {
        const ids = collections.filter((c) => c.monitored !== monitored).map((c) => c.id);
        const result = await runBulkCollections(
          {
            collection_ids: ids,
            operation: "set_monitored",
            monitored,
          },
          (body) => collectionsRequest.mutateAsync({ body }),
        );
        bulkSetCollectionMonitoredInCache(result.collection_ids, monitored);
        feedback.success(
          `${monitored ? "Monitored" : "Unmonitored"} ${result.collection_ids.length} collections.`,
        );
        for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
      }
    } catch (err: unknown) {
      feedback.error(errorMessage(err, `Failed to ${actionWord.toLowerCase()}`));
    }
  }
  /** Remove the art or themes of every matching collection. */
  async function removeCollectionAssets(operation: "remove_artwork" | "remove_themes") {
    if (busy || !resultsReady || forItems || !collections.length) return;
    const ids = collections.map((collection) => collection.id);
    const what = operation === "remove_artwork" ? "art" : "themes";
    feedback.clear();
    try {
      const removal = await askRemoval(
        { asset: operation === "remove_artwork" ? "art" : "theme", collection_ids: ids },
        `the ${what} of ${ids.length} filtered collections`,
      );
      if (!removal) return;
      const result = await runBulkCollections(
        { collection_ids: ids, operation, removal },
        (body) => collectionsRequest.mutateAsync({ body }),
      );
      feedback.success(
        removedMessage(
          `the ${what} of ${result.collection_ids.length} collections`,
          removal,
          true,
        ),
      );
      for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
    } catch (error) {
      feedback.error(errorMessage(error, "Bulk operation failed"));
    }
  }

  let collectionOperation = $state<BulkCollectionOperation["operation"]>("set_group");
  // A set's collections leave only with their set, which would make them again.
  let operationTargets = $derived(
    collectionOperation === "adopt"
      ? unmanagedCollections
      : collectionOperation === "delete" || collectionOperation === "orphan"
        ? collections.filter(
            (row) =>
              row.generated_value === null && (collectionOperation === "delete" || !row.withheld),
          )
        : collections,
  );
  let targetGroup = $state(UNGROUPED_GROUP);
  const INHERIT_LABEL = "Inherit group or global default";
  const VISIBILITY_OPTIONS: SelectOption<CollectionMode | null>[] = [
    { value: null, label: INHERIT_LABEL },
    { value: "hide", label: "Hide collection" },
    { value: "hide_items", label: "Hide items" },
    { value: "default", label: "Library default" },
    { value: "show_items", label: "Show collection and items" },
  ];
  let targetGroups = $derived(groupOptions(groupsQuery.data ?? []));
  /** The operations, by label, each disabled while it has no collections to act on. */
  let collectionOperations = $derived.by(() => {
    const operations: SelectOption<BulkCollectionOperation["operation"]>[] = [
        { value: "adopt", label: "Adopt unmanaged", disabled: !unmanagedCollections.length },
        { value: "orphan", label: "Orphan managed", disabled: !collections.length },
        { value: "set_group", label: "Assign group", disabled: !collections.length },
        { value: "set_order", label: "Set sort", disabled: !collections.length },
        {
          value: "apply_sort_title_format",
          label: "Format sort titles",
          disabled: !collections.length,
        },
        ...(capabilities.data?.visibility
          ? [
              {
                value: "set_visibility" as const,
                label: "Set visibility",
                disabled: !collections.length,
              },
            ]
          : []),
      { value: "delete", label: "Delete collections", disabled: !collections.length },
    ];
    return operations.toSorted((a, b) => a.label.localeCompare(b.label));
  });
  let orderOptions = $derived<SelectOption<CollectionOrder | null>[]>([
    { value: null, label: INHERIT_LABEL },
    ...sortedOrders(capabilities.data?.orders ?? []).map((entry) => ({
      value: entry,
      label: ORDER_LABELS[entry],
    })),
  ]);
  let template = $state("{title}");
  let visibility = $state<CollectionMode | null>(null);
  let home = $state(false);
  let order = $state<CollectionOrder | null>(null);

  const id = $props.id();

  /** Ask before running the operation; deletion also asks where to delete. */
  async function confirmCollectionOperation(
    operation: BulkCollectionOperation["operation"],
    count: number,
  ): Promise<Partial<Pick<BulkCollectionOperation, "delete_target">> | null> {
    if (operation === "delete") {
      const target = await chooseAction<NonNullable<BulkCollectionOperation["delete_target"]>>({
        title: `Delete ${count} filtered collections?`,
        message: "Choose where to delete them. Movies, shows and media files are always kept.",
        confirmLabel: "Delete collections",
        destructive: true,
        choices: [
          {
            value: "server",
            label: `From ${settingsState.media_server_name} only`,
            description: "Overture keeps their configuration, so a later sync can recreate them.",
          },
          { value: "both", label: `From Overture and ${settingsState.media_server_name}` },
        ],
      });
      return target ? { delete_target: target } : null;
    }
    const confirmed = await confirmAction({
      title: `Apply to ${count} filtered collections?`,
      message:
        operation === "orphan"
          ? "Overture stops managing them and lists them under Unmanaged. The media server keeps them as they are."
          : "Apply the chosen operation to every collection matching these filters and the open group.",
      confirmLabel: operation === "orphan" ? "Orphan" : "Apply",
    });
    return confirmed ? {} : null;
  }

  async function runCollectionOperation() {
    if (busy || !resultsReady || !operationTargets.length) return;
    const operation = collectionOperation;
    const ids = operationTargets.map((collection) => collection.id);
    const answer = await confirmCollectionOperation(operation, ids.length);
    if (!answer) return;
    const body: BulkCollectionOperation = {
      ...answer,
      collection_ids: ids,
      operation,
    };
    if (operation === "set_group" || operation === "adopt") {
      body.collection_group = targetGroup || null;
    }
    if (operation === "apply_sort_title_format") body.sort_title_format = template;
    if (operation === "set_order") body.order_type = order;
    if (operation === "set_visibility") {
      body.collection_mode = visibility;
      body.visible_home = home;
    }
    try {
      const result = await runBulkCollections(body, (body) =>
        collectionsRequest.mutateAsync({ body }),
      );
      feedback.success(`Updated ${result.collection_ids.length} collections.`);
      for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
    } catch (error) {
      feedback.error(errorMessage(error, "Collection operation failed"));
    }
  }
</script>

<PopupSection
  label="Bulk operations"
  description={resultsReady
    ? `For the ${matchCount} ${noun} the filters and search match. Local files are kept.`
    : `Matching ${noun} are unavailable or still loading.`}
>
  <div class="action-card-buttons">
    <button
      type="button"
      class="btn btn-secondary btn-sm"
      onclick={() => setMonitored(true)}
      disabled={unmonitoredCount === 0 || busy || !resultsReady}
    >
      {#if running?.operation === "monitor"}
        Monitoring...
      {:else}
        Monitor <span class="operation-count">{unmonitoredCount}</span>
      {/if}
    </button>
    <button
      type="button"
      class="btn btn-secondary btn-sm"
      onclick={() => setMonitored(false)}
      disabled={monitoredCount === 0 || busy || !resultsReady}
    >
      {#if running?.operation === "unmonitor"}
        Unmonitoring...
      {:else}
        Unmonitor <span class="operation-count">{monitoredCount}</span>
      {/if}
    </button>
    {#if forItems}
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        title="Season posters included"
        onclick={() => runItemOperation("artwork")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Remove art <span class="operation-count">{matchCount}</span>
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        onclick={() => runItemOperation("themes")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Remove themes <span class="operation-count">{matchCount}</span>
      </button>
      <button
        type="button"
        class="btn btn-danger btn-sm"
        onclick={() => runItemOperation("delete")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Delete from Overture <span class="operation-count">{matchCount}</span>
      </button>
    {:else}
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        onclick={() => void removeCollectionAssets("remove_artwork")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Remove art <span class="operation-count">{matchCount}</span>
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        onclick={() => void removeCollectionAssets("remove_themes")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Remove themes <span class="operation-count">{matchCount}</span>
      </button>
    {/if}
  </div>
  {#if running && running.operation !== "monitor" && running.operation !== "unmonitor"}
    <p class="action-feedback" role="status">
      {running.operation === "delete"
        ? `Deleting ${noun}`
        : forItems
          ? `Removing ${running.operation === "artwork" ? "art" : "themes"}`
          : "Updating collections"}:
      {running.count}
      {noun}...
    </p>
  {/if}
</PopupSection>

{#if !forItems}
  <PopupSection
    label="Collection operations"
    description="For the collections the filters, search and open group match."
  >
    <FieldRow label="Operation" for={`${id}-operation`}>
      <Select
        id={`${id}-operation`}
        disabled={busy || !resultsReady || !matchedCollections.length}
        options={collectionOperations}
        bind:value={collectionOperation}
      />
    </FieldRow>
    {#if collectionOperation === "set_group" || collectionOperation === "adopt"}
      <FieldRow label="Target group" for={`${id}-group`}>
        <Select
          id={`${id}-group`}
          disabled={busy}
          options={targetGroups}
          bind:value={targetGroup}
        />
      </FieldRow>
      <DataStatus
        label="collection groups"
        error={groupsQuery.error}
        loading={groupsQuery.isFetching}
        hasData={groupsQuery.data !== undefined}
        onretry={() => groupsQuery.refetch()}
      />
    {:else if collectionOperation === "orphan"}
      <p class="hint">
        Overture forgets their criteria, group and schedule and lists them under Unmanaged; the
        media server keeps them as they are.
      </p>
    {:else if collectionOperation === "apply_sort_title_format"}
      <FieldRow
        label="Sort title template"
        for={`${id}-template`}
        hint="Use &#123;title&#125; and &#123;group&#125;."
      >
        <input id={`${id}-template`} maxlength={TEXT_LIMITS.sortTitleFormat} bind:value={template} disabled={busy} />
      </FieldRow>
    {:else if collectionOperation === "set_order"}
      <FieldRow
        label="Sort"
        for={`${id}-order`}
        hint={capabilities.data?.smart ? "Smart collections cannot use a custom order." : undefined}
      >
        <Select
          id={`${id}-order`}
          disabled={busy}
          options={orderOptions}
          bind:value={order}
        />
      </FieldRow>
    {:else if collectionOperation === "set_visibility"}
      <FieldRow label="Visibility" for={`${id}-visibility`}>
        <Select
          id={`${id}-visibility`}
          disabled={busy}
          options={VISIBILITY_OPTIONS}
          bind:value={visibility}
        />
      </FieldRow>
      <FieldRow label="Visible on home" for={`${id}-home`}>
        <input id={`${id}-home`} type="checkbox" bind:checked={home} disabled={busy} />
      </FieldRow>
    {/if}
    <button
      type="button"
      class={["btn btn-sm self-end", collectionOperation === "delete" ? "btn-danger" : "btn-secondary"]}
      disabled={busy || !resultsReady || !operationTargets.length}
      onclick={() => void runCollectionOperation()}
      >Apply to <span class="operation-count">{operationTargets.length}</span> collections</button
    >
  </PopupSection>
{/if}

<style>
  /* Even pairs; the destructive action takes a line of its own, last. */
  .action-card-buttons {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .action-card-buttons .btn-danger {
    grid-column: 1 / -1;
  }
  .operation-count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    opacity: 0.75;
  }
  .action-feedback {
    margin-top: var(--space-1);
    font-size: var(--text-xs);
  }
</style>
