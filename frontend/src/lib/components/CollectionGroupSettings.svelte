<script lang="ts">
  import { countOf } from "../utils/plural";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { onMount, type Snippet } from "svelte";
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    applyCollectionGroupPolicyMutation,
    getCollectionDefaultsOptions,
    getCollectionGroupPolicyOptions,
    listCollectionsOptions,
    saveCollectionGroupPolicyMutation,
    syncCollectionGroupMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { UNGROUPED_GROUP } from "../../generated/settings";
  import type {
    CollectionGroupPolicyInput,
    LibrarySectionRead,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  import { defaultGenerator, type SetGenerator } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import { CollectionOptions } from "../utils/libraries.svelte";
  import { availableOrders } from "../utils/collectionCriteria";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import DataStatus from "./DataStatus.svelte";
  import DetailForm from "./DetailForm.svelte";

  let {
    group,
    libraries = [],
    onsave,
    onfooterchange,
  }: {
    group: string;
    libraries?: LibrarySectionRead[];
    /** The group is saved, so it exists from now on. */
    onsave?: () => void;
    /** Hand the popup the save actions, which belong in its footer, until unmounted. */
    onfooterchange?: (footer: Snippet | null) => void;
  } = $props();

  // Every group opens with its sections closed.
  sectionState.forget(getSectionView());

  onMount(() => {
    onfooterchange?.(actions);
    return () => onfooterchange?.(null);
  });

  const client = useQueryClient();
  const query = createQuery(() => ({
    ...getCollectionGroupPolicyOptions({ query: { name: group } }),
    enabled: !!group.trim(),
  }));
  const defaults = createQuery(() => getCollectionDefaultsOptions());
  const options = new CollectionOptions();
  const request = createMutation(() => saveCollectionGroupPolicyMutation());
  const syncRequest = createMutation(() => syncCollectionGroupMutation());
  const applyRequest = createMutation(() => applyCollectionGroupPolicyMutation());
  const feedback = createNotifier();

  type GroupDraft = Omit<CollectionGroupPolicyInput, "generator"> & {
    generator: SetGenerator | null;
  };
  // Seeded once: a refetch, such as one a sync's broadcasts start, never undoes an edit.
  let draft = $state<GroupDraft | null>(null);
  $effect(() => {
    if (query.data && draft === null) draft = structuredClone($state.snapshot(query.data));
  });
  const collections = createQuery(() => listCollectionsOptions());
  /** A set offers what its libraries share, a group what its collections do; an empty one both. */
  let mediaTypes = $derived.by<MediaType[]>(() => {
    const held = new Set<MediaType>(
      draft?.generator
        ? libraries
            .filter((library) => draft?.generator?.library_ids.includes(library.id))
            .map((library) => library.media_type)
        : (collections.data ?? [])
            .filter((row) => row.collection_group === group)
            .flatMap((row) => row.media_types),
    );
    return held.size ? [...held] : ["movie", "show"];
  });
  let capabilities = $derived(options.shared(mediaTypes));
  let arr = $derived(
    capabilities?.arr
      ? mediaTypes.map((type) => (type === "movie" ? "Radarr" : "Sonarr")).join(" and ")
      : null,
  );
  let busy = $derived(request.isPending || syncRequest.isPending || applyRequest.isPending);
  let hasMembers = $derived(
    (collections.data ?? []).some((row) => row.managed && row.collection_group === group),
  );
  /** Why the group has nothing to send to the server yet, or null when it has. */
  let serverBlocker = $derived(
    hasMembers || draft?.generator ? null : "The group has no collections yet",
  );

  /** Save in Overture; `then` applies the defaults or syncs the group on the server. */
  async function save(then?: "apply" | "sync") {
    if (!draft || busy) return;
    const variables = {
      query: { name: group },
      body: $state.snapshot(draft),
    };
    try {
      const saved = await request.mutateAsync(variables);
      client.setQueryData(
        getCollectionGroupPolicyOptions({ query: variables.query }).queryKey,
        saved,
      );
      onsave?.();
      if (then === "sync") return await sync();
      if (!then) {
        feedback.success("Saved. Collections use it from their next sync.");
        return;
      }
      const result = await applyRequest.mutateAsync({ query: variables.query });
      const errors = Object.values(result.errors);
      if (errors.length) {
        feedback.error(
          `Applied to ${result.collection_ids.length} collections. ${errors.length} failed: ${errors.join("; ")}`,
        );
        return;
      }
      feedback.success(
        `Saved and applied to ${countOf(result.collection_ids.length, "collection")}.`,
      );
    } catch (error) {
      feedback.error(errorMessage(error, "Could not save the group"));
    }
  }

  async function sync() {
    try {
      const result = await syncRequest.mutateAsync({
        query: { name: group },
      });
      const errors = Object.entries(result.errors);
      const summary = `${result.created.length} created, ${result.withheld.length} taken off the server, ${result.synced} synced`;
      if (errors.length) {
        feedback.error(
          `${summary}. ${errors.length} failed: ${errors.map(([title, error]) => `${title}: ${error}`).join("; ")}`,
        );
      } else {
        feedback.success(`Saved and synced: ${summary}.`);
      }
    } catch (error) {
      feedback.error(errorMessage(error, "Could not sync the group"));
    }
  }
</script>

<DataStatus
  label="group"
  error={query.error}
  loading={query.isFetching}
  hasData={query.data !== undefined}
  onretry={() => query.refetch()}
/>
<DataStatus
  label="collection options"
  error={options.for("movie").error}
  loading={options.for("movie").isFetching}
  hasData={options.for("movie").data !== undefined}
  onretry={() => options.for("movie").refetch()}
/>
{#if draft}
  {@const form = draft}
  <!-- Ungrouped holds collections without a group, so it never creates any. -->
  {#if group !== UNGROUPED_GROUP}<DetailForm
    collapsible
    title="Collection set"
    description="One collection in this group per value in a library, such as each decade, kept up to date."
    {busy}
  >
    <label class="form-row">
      <input
        type="checkbox"
        checked={!!form.generator}
        onchange={(event) =>
          (form.generator = event.currentTarget.checked
            ? defaultGenerator(libraries.slice(0, 1).map((library) => library.id))
            : null)}
      />
      Create this group's collections
    </label>
    {#if form.generator}
      {@const generator = form.generator}
      <fieldset class="libraries">
        <legend class="form-label">Libraries</legend>
        {#each libraries as library (library.id)}
          <label class="form-row">
            <input
              type="checkbox"
              checked={generator.library_ids.includes(library.id)}
              onchange={(event) =>
                (generator.library_ids = event.currentTarget.checked
                  ? [...generator.library_ids, library.id]
                  : generator.library_ids.filter((id) => id !== library.id))}
            />
            {library.title}
          </label>
        {/each}
      </fieldset>
      <CollectionSetEditor
        bind:generator={draft.generator!}
        libraryIds={generator.library_ids}
        {libraries}
        {capabilities}
        {group}
        minimum={form.minimum_items ?? null}
        standalone
      />
    {/if}
  </DetailForm>{/if}
  <DetailForm
    collapsible
    title="Settings"
    description="Collections in the group inherit these unless they set their own."
    {busy}
  >
    <CollectionPolicyFields
      bind:policy={draft}
      level="group"
      defaults={defaults.data}
      plex={capabilities?.visibility ?? false}
      orders={availableOrders(capabilities, !!form.generator?.smart)}
      {arr}
      memberLabels={capabilities?.member_labels ?? false}
    />
  </DetailForm>
  <DetailForm
    collapsible
    title="Schedule"
    description="When the group's collections sync, and when they are active each year."
    {busy}
  >
    <CollectionScheduleFields bind:policy={draft} level="group" defaults={defaults.data} />
  </DetailForm>
{/if}

{#snippet actions()}
  {#if draft}
    <button
      type="button"
      class="btn btn-secondary"
      title={hasMembers
        ? "Send the defaults to the server without changing members"
        : "The group has no collections yet"}
      disabled={busy || !hasMembers}
      onclick={() => void save("apply")}>Save and Apply</button
    >
    <button
      type="button"
      class="btn btn-secondary"
      title={serverBlocker ?? undefined}
      disabled={busy || !!serverBlocker}
      onclick={() => void save("sync")}
    >
      <RefreshCw size={14} class={syncRequest.isPending ? "animate-spin" : ""} />
      Save and Sync
    </button>
    <button type="button" class="btn btn-primary" disabled={busy} onclick={() => void save()}
      >Save</button
    >
  {/if}
{/snippet}

<style>
  .libraries {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .libraries legend {
    width: 100%;
    padding: 0;
  }
</style>
