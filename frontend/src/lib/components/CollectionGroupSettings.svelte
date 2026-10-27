<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    applyCollectionGroupPolicyMutation,
    getCollectionCapabilitiesOptions,
    getCollectionDefaultsOptions,
    getCollectionGroupPolicyOptions,
    saveCollectionGroupPolicyMutation,
    syncCollectionGroupMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionGroupPolicyInput,
    LibrarySectionRead,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { defaultGenerator, type SetGenerator } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import { availableOrders } from "../utils/collectionCriteria";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import DataStatus from "./DataStatus.svelte";
  import DetailForm from "./DetailForm.svelte";

  let {
    group,
    mediaType,
    libraries = [],
    onsave,
  }: {
    group: string;
    mediaType: MediaType;
    libraries?: LibrarySectionRead[];
    /** The group is saved, so it exists from now on. */
    onsave?: () => void;
  } = $props();

  const client = useQueryClient();
  const query = createQuery(() => ({
    ...getCollectionGroupPolicyOptions({ query: { name: group, media_type: mediaType } }),
    enabled: !!group.trim(),
  }));
  const defaults = createQuery(() =>
    getCollectionDefaultsOptions({ query: { media_type: mediaType } }),
  );
  const capabilities = createQuery(() =>
    getCollectionCapabilitiesOptions({ query: { media_type: mediaType } }),
  );
  const request = createMutation(() => saveCollectionGroupPolicyMutation());
  const syncRequest = createMutation(() => syncCollectionGroupMutation());
  const applyRequest = createMutation(() => applyCollectionGroupPolicyMutation());
  const feedback = createNotifier();

  type GroupDraft = Omit<CollectionGroupPolicyInput, "generator"> & {
    generator: SetGenerator | null;
  };
  let draft = $derived.by(() => {
    if (!query.data) return null;
    const value = $state<GroupDraft>(structuredClone(query.data));
    return value;
  });
  let busy = $derived(request.isPending || syncRequest.isPending || applyRequest.isPending);

  /** Save in Overture; `then` applies the defaults or syncs the group on the server. */
  async function save(then?: "apply" | "sync") {
    if (!draft || busy) return;
    const variables = {
      query: { name: group, media_type: mediaType },
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
        `Saved and applied to ${result.collection_ids.length} collection${result.collection_ids.length === 1 ? "" : "s"}.`,
      );
    } catch (error) {
      feedback.error(errorMessage(error, "Could not save the group"));
    }
  }

  async function sync() {
    try {
      const result = await syncRequest.mutateAsync({
        query: { name: group, media_type: mediaType },
      });
      const errors = Object.entries(result.errors);
      const summary = `${result.created.length} created, ${result.removed.length} removed, ${result.synced} synced`;
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
  error={capabilities.error}
  loading={capabilities.isFetching}
  hasData={capabilities.data !== undefined}
  onretry={() => capabilities.refetch()}
/>
{#if draft}
  {@const form = draft}
  <DetailForm
    collapsible
    expanded={!!form.generator}
    title="Collection set"
    description="One collection in this group per value in a library, such as each decade, kept up to date."
    {busy}
  >
    <label class="form-row form-wide">
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
      <fieldset class="libraries form-wide">
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
        {generator}
        libraryIds={generator.library_ids}
        {libraries}
        {mediaType}
        capabilities={capabilities.data}
        {group}
        minimum={form.minimum_items ?? null}
        titled
      />
    {/if}
  </DetailForm>
  <DetailForm
    collapsible
    title="Settings"
    description="Collections in the group inherit these unless they set their own."
    {busy}
  >
    <CollectionPolicyFields
      policy={form}
      level="group"
      defaults={defaults.data}
      plex={capabilities.data?.visibility ?? false}
      orders={availableOrders(capabilities.data, !!form.generator?.smart)}
      arr={capabilities.data?.arr ? (mediaType === "movie" ? "Radarr" : "Sonarr") : null}
      memberLabels={capabilities.data?.member_labels ?? false}
    />
  </DetailForm>
  <DetailForm
    collapsible
    title="Schedule"
    description="When the group's collections sync, and when they are active each year."
    {busy}
  >
    <CollectionScheduleFields policy={form} level="group" defaults={defaults.data} />
  </DetailForm>
  <div class="actions" role="group" aria-label="Group actions">
    <button type="button" class="btn btn-primary" disabled={busy} onclick={() => void save()}
      >Save</button
    >
    <button
      type="button"
      class="btn btn-secondary"
      title="Send the defaults to the server without changing members"
      disabled={busy}
      onclick={() => void save("apply")}>Save and Apply</button
    >
    <button
      type="button"
      class="btn btn-secondary"
      disabled={busy}
      onclick={() => void save("sync")}
    >
      <RefreshCw size={14} class={syncRequest.isPending ? "animate-spin" : ""} />
      Save and Sync
    </button>
  </div>
{/if}

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

  .actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-3);
  }
</style>
