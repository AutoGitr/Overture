<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionCapabilitiesOptions,
    listCollectionsOptions,
    listCollectionGroupsOptions,
    listItemsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
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
  import { uiState, type FilterState } from "../stores/uiState.svelte";
  import { sidebarGroup } from "../router/routes";
  import { runBulkCollections } from "../utils/bulkCollections";
  import { ORDER_LABELS, sortedOrders } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import { UNGROUPED_GROUP } from "../../generated/settings";
  import { CollectionMembers } from "../utils/collectionMembers.svelte";
  import DataStatus from "./DataStatus.svelte";
  import FieldRow from "./FieldRow.svelte";
  import {
    filterSidebarCollections,
    filterSidebarItems,
    hasThemeAttributes,
    inCollectionGroup,
  } from "../utils/sidebarDomain";

  /** A request the popup owns, so its other actions wait while one runs. */
  interface Request<TBody, TResult> {
    mutateAsync: (variables: { body: TBody }) => Promise<TResult>;
    isPending: boolean;
    variables: { body: TBody } | undefined;
  }

  /** Operations on everything the filters and search currently match. */
  let {
    filters,
    publicDatasetEnabled,
    itemsRequest,
    collectionsRequest,
  }: {
    /** The filters being edited, not yet applied to the sidebar. */
    filters: FilterState;
    publicDatasetEnabled: boolean;
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

  const filteredCollection = new CollectionMembers(() =>
    uiState.sidebarMode === "items" ? filters.collectionId : null,
  );
  let items: MediaItemRead[] = $derived(
    uiState.sidebarMode === "items"
      ? filterSidebarItems({
          items: itemsQuery.data?.items ?? [],
          filters,
          publicDatasetEnabled,
          collectionMembers: filteredCollection.ids,
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
          publicDatasetEnabled,
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
  let itemsWithThemes = $derived(items.filter(hasThemeAttributes));

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

  const CONFIRMATIONS: Record<
    ItemOperation,
    (target: string) => Parameters<typeof confirmAction>[0]
  > = {
    delete: (target) => ({
      title: `Delete ${target}?`,
      message:
        "Their saved records will be removed from Overture. Local files and media server items will be kept. Items still on the media server may return after a sync.",
      confirmLabel: "Delete",
      destructive: true,
    }),
    artwork: (target) => ({
      title: `Forget artwork for ${target}?`,
      message:
        "Saved artwork selections, including season posters, will be forgotten. Local artwork files and what Overture knows about them are kept.",
      confirmLabel: "Forget artwork",
      destructive: true,
    }),
    themes: (target) => ({
      title: `Forget themes for ${target}?`,
      message:
        "Saved theme selections and YouTube details will be removed. Local theme files are kept.",
      confirmLabel: "Forget themes",
      destructive: true,
    }),
  };

  async function runItemOperation(operation: ItemOperation) {
    if (busy || !resultsReady || !forItems) return;
    const ids = (operation === "themes" ? itemsWithThemes : items).map((item) => item.id);
    if (ids.length === 0) return;
    if (!(await confirmAction(CONFIRMATIONS[operation](`${ids.length} filtered ${noun}`)))) return;

    feedback.clear();
    try {
      const result = await itemsRequest.mutateAsync({ body: { item_ids: ids, operation } });
      applyBulkItemOperation(result);
      const count = result.item_ids.length;
      feedback.success(
        operation === "delete"
          ? `Deleted ${count} ${noun} from Overture.`
          : `Cleared ${operation === "artwork" ? "artwork" : "theme"} selections for ${count} ${noun}.`,
      );
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
  let collectionsWithThemes = $derived(collections.filter(hasThemeAttributes));

  /** Forget the art or theme choices of every matching collection. */
  async function clearCollections(operation: "clear_artwork" | "clear_themes") {
    const targets = operation === "clear_themes" ? collectionsWithThemes : collections;
    if (busy || !resultsReady || forItems || !targets.length) return;
    const target = `${targets.length} filtered collections`;
    const confirmed = await confirmAction(
      CONFIRMATIONS[operation === "clear_artwork" ? "artwork" : "themes"](target),
    );
    if (!confirmed) return;
    feedback.clear();
    try {
      const result = await runBulkCollections(
        {
          collection_ids: targets.map((collection) => collection.id),
          operation,
        },
        (body) => collectionsRequest.mutateAsync({ body }),
      );
      feedback.success(
        `Cleared ${operation === "clear_artwork" ? "artwork" : "theme"} selections for ${result.collection_ids.length} collections.`,
      );
      for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
    } catch (error) {
      feedback.error(errorMessage(error, "Bulk operation failed"));
    }
  }

  let collectionOperation = $state<BulkCollectionOperation["operation"]>("set_group");
  let operationTargets = $derived(
    collectionOperation === "adopt" ? unmanagedCollections : collections,
  );
  let targetGroup = $state(UNGROUPED_GROUP);
  let targetGroups = $derived(
    [...new Set([UNGROUPED_GROUP, ...(groupsQuery.data ?? [])])].sort((a, b) =>
      a.localeCompare(b),
    ),
  );
  /** The operations, by label, with whether each has collections to act on. */
  let collectionOperations = $derived(
    (
      [
        ["adopt", "Adopt unmanaged", !unmanagedCollections.length],
        ["orphan", "Orphan managed", !collections.length],
        ["set_group", "Assign group", !collections.length],
        ["set_order", "Set sort", !collections.length],
        ["apply_sort_title_format", "Format sort titles", !collections.length],
        ...(capabilities.data?.visibility
          ? [["set_visibility", "Set visibility", !collections.length] as const]
          : []),
        ["delete", "Delete collections", !collections.length],
      ] as const satisfies readonly (readonly [BulkCollectionOperation["operation"], string, boolean])[]
    ).toSorted((a, b) => a[1].localeCompare(b[1])),
  );
  let template = $state("{title}");
  let visibility = $state<CollectionMode | null>(null);
  let home = $state(false);
  let order = $state<CollectionOrder>("release.asc");

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
            label: "From the media server only",
            description: "Overture keeps their configuration, so a later sync can recreate them.",
          },
          { value: "both", label: "From Overture and the media server" },
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

<section class="option-card action-card" aria-label="Bulk operations">
  <div class="heading-row">
    <h3 class="form-label">Bulk operations</h3>
    <span class="hint">
      {resultsReady
        ? `For the ${matchCount} ${noun} the filters and search match. Local files are kept.`
        : `Matching ${noun} are unavailable or still loading.`}
    </span>
  </div>
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
        Clear artwork selections <span class="operation-count">{matchCount}</span>
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        title="Clears the saved YouTube details"
        onclick={() => runItemOperation("themes")}
        disabled={itemsWithThemes.length === 0 || busy || !resultsReady}
      >
        Clear theme selections <span class="operation-count">{itemsWithThemes.length}</span>
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
        onclick={() => void clearCollections("clear_artwork")}
        disabled={matchCount === 0 || busy || !resultsReady}
      >
        Clear artwork selections <span class="operation-count">{matchCount}</span>
      </button>
      <button
        type="button"
        class="btn btn-secondary btn-sm"
        title="Clears the saved YouTube details"
        onclick={() => void clearCollections("clear_themes")}
        disabled={collectionsWithThemes.length === 0 || busy || !resultsReady}
      >
        Clear theme selections <span class="operation-count">{collectionsWithThemes.length}</span>
      </button>
    {/if}
  </div>
  {#if running && running.operation !== "monitor" && running.operation !== "unmonitor"}
    <p class="action-feedback" role="status">
      {running.operation === "delete"
        ? `Deleting ${noun}`
        : forItems
          ? `Clearing ${running.operation === "artwork" ? "artwork" : "theme"} selections`
          : "Updating collections"}:
      {running.count}
      {noun}...
    </p>
  {/if}
</section>

{#if !forItems}
  <section
    class="option-card"
    aria-label="Collection operations"
  >
    <div class="heading-row">
      <h3 class="form-label">Collection operations</h3>
      <span class="hint">For the collections the filters, search and open group match.</span>
    </div>
    <FieldRow label="Operation" for={`${id}-operation`}>
      <select
        id={`${id}-operation`}
        bind:value={collectionOperation}
        disabled={busy || !resultsReady || !matchedCollections.length}
      >
        {#each collectionOperations as [value, label, disabled] (value)}
          <option {value} {disabled}>{label}</option>
        {/each}
      </select>
    </FieldRow>
    {#if collectionOperation === "set_group" || collectionOperation === "adopt"}
      <FieldRow label="Target group" for={`${id}-group`}>
        <select id={`${id}-group`} bind:value={targetGroup} disabled={busy}>
          {#each targetGroups as group (group)}<option value={group}>{group}</option>{/each}
        </select>
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
        <input id={`${id}-template`} maxlength="200" bind:value={template} disabled={busy} />
      </FieldRow>
    {:else if collectionOperation === "set_order"}
      <FieldRow
        label="Sort"
        for={`${id}-order`}
        hint={capabilities.data?.smart ? "Smart collections cannot use a custom order." : undefined}
      >
        <select id={`${id}-order`} bind:value={order} disabled={busy}
          >{#each sortedOrders(capabilities.data?.orders ?? []) as entry (entry)}<option value={entry}
              >{ORDER_LABELS[entry]}</option
            >{/each}</select
        >
      </FieldRow>
    {:else if collectionOperation === "set_visibility"}
      <FieldRow label="Visibility" for={`${id}-visibility`}>
        <select id={`${id}-visibility`} bind:value={visibility} disabled={busy}
          ><option value={null}>Inherit group or global default</option><option value="hide"
            >Hide collection</option
          ><option value="hide_items">Hide items</option><option value="default"
            >Library default</option
          ><option value="show_items">Show collection and items</option></select
        >
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
  </section>
{/if}

<style>
  .action-card {
    border: var(--border-muted);
  }

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
