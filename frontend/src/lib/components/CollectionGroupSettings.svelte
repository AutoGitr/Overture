<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { onMount, type Snippet } from "svelte";
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    getCollectionDefaultsOptions,
    getCollectionGroupPolicyOptions,
    listCollectionsOptions,
    saveCollectionGroupPolicyMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { UNGROUPED_GROUP } from "../../generated/settings";
  import type {
    CollectionGroupPolicyInput,
    LibrarySectionRead,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { defaultGenerator, type SetGenerator } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import { openSync } from "../utils/syncShortcut";
  import { CollectionOptions } from "../utils/libraries.svelte";
  import { availableOrders } from "../utils/collectionCriteria";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import DataStatus from "./DataStatus.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";

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
  let busy = $derived(request.isPending);
  let hasMembers = $derived(
    (collections.data ?? []).some((row) => row.managed && row.collection_group === group),
  );
  /** Why the group has nothing to send to the server yet, or null when it has. */
  let serverBlocker = $derived(
    hasMembers || draft?.generator ? null : "The group has no collections yet",
  );

  /**
   * Save the group in Overture; with `sync`, then open Sync with only this
   * group chosen, which sends its settings to its collections.
   */
  async function save(sync = false) {
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
      if (sync) return await openSync({ groups: [group] });
      feedback.success(
        hasMembers
          ? "Saved. Its collections get it on the server with their next sync."
          : "Saved. Its collections use it once they are made.",
      );
    } catch (error) {
      feedback.error(errorMessage(error, "Could not save the group"));
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
    <!-- Only Plex keeps empty collections, which a separator is. -->
    {#if group !== UNGROUPED_GROUP && settingsState.current.media_server === "plex"}
      <FieldRow
        label="Separator"
        hint="An empty collection titled after the group, with generated art, sorted right before the group's collections. Without a sort title set anywhere, they sort as {'{group} {title}'}; one that puts the group first keeps it there."
      >
        <input type="checkbox" aria-label="Separator" bind:checked={form.separator} />
      </FieldRow>
    {/if}
  </DetailForm>
  <DetailForm
    collapsible
    title="Active dates"
    description="When the group's collections are on the server each year."
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
      title={serverBlocker ?? "Save, then open Sync in Operations with only this group chosen"}
      disabled={busy || !!serverBlocker}
      onclick={() => void save(true)}
    >
      <RefreshCw size={14} />
      Save and Sync
    </button>
    <button
      type="button"
      class="btn btn-primary"
      title="Save in Overture; the group's next sync sends the settings to its collections"
      disabled={busy}
      onclick={() => void save()}>Save</button
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
