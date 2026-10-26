<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    getCollectionGroupPolicyOptions,
    saveCollectionGroupPolicyMutation,
    syncCollectionGroupMutation,
    applyCollectionGroupPolicyMutation,
    getCollectionDefaultsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionGroupPolicyOutput,
    LibrarySectionRead,
    MediaType,
    ServerType,
  } from "../../generated/rest/types.gen";
  import DetailForm from "./DetailForm.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DataStatus from "./DataStatus.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import CollectionDiscoveryFields from "./CollectionDiscoveryFields.svelte";
  import { errorMessage } from "../utils/errors";

  let {
    group,
    mediaType,
    serverType,
    libraries = [],
  }: {
    group: string;
    mediaType: MediaType;
    serverType: ServerType | null;
    libraries?: LibrarySectionRead[];
  } = $props();

  const client = useQueryClient();
  const query = createQuery(() => ({
    ...getCollectionGroupPolicyOptions({ query: { name: group, media_type: mediaType } }),
    enabled: !!group.trim(),
  }));
  const request = createMutation(() => saveCollectionGroupPolicyMutation());
  const syncGroupRequest = createMutation(() => syncCollectionGroupMutation());
  const feedback = createNotifier();
  const applyRequest = createMutation(() => applyCollectionGroupPolicyMutation());
  const defaults = createQuery(() =>
    getCollectionDefaultsOptions({ query: { media_type: mediaType } }),
  );

  let draft = $derived.by(() => {
    if (!query.data) return null;
    const value = $state<CollectionGroupPolicyOutput>({
      ...query.data,
      dynamic_tmdb: query.data.dynamic_tmdb
        ? {
            ...query.data.dynamic_tmdb,
            exclude_tmdb_ids: [...query.data.dynamic_tmdb.exclude_tmdb_ids],
          }
        : null,
    });
    return value;
  });

  async function save(apply = false) {
    if (!draft || request.isPending) return;
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
      if (apply) {
        const result = await applyRequest.mutateAsync({ query: variables.query });
        const errors = Object.values(result.errors);
        if (errors.length) {
          feedback.error(
            `Applied to ${result.collection_ids.length} collections. ${errors.length} failed: ${errors.join("; ")}`,
          );
          return;
        }
        feedback.success(
          `Group defaults applied to ${result.collection_ids.length} collection${result.collection_ids.length === 1 ? "" : "s"}. Explicit overrides were kept.`,
        );
      } else {
        feedback.success("Group defaults saved. Collections use them on their next save or sync.");
      }
    } catch (error) {
      feedback.error(errorMessage(error, "Could not save group defaults"));
    }
  }

  async function syncGroup() {
    if (syncGroupRequest.isPending) return;
    try {
      await syncGroupRequest.mutateAsync({ query: { name: group, media_type: mediaType } });
      feedback.success(`Group "${group}" collections synced.`);
    } catch (error) {
      feedback.error(errorMessage(error, "Failed to sync collection group"));
    }
  }

  function toggleDynamicTmdb(enabled: boolean) {
    if (!draft) return;
    if (enabled) {
      draft.dynamic_tmdb = {
        enabled: true,
        library_id: libraries[0]?.id ?? "",
        strip_prefix: "The ",
        strip_suffix: " Collection",
        auto_exclude_from_other_collections: true,
        exclude_tmdb_ids: [],
      };
    } else {
      draft.dynamic_tmdb = null;
    }
  }
</script>

<DetailForm
  collapsible
  title="Group settings"
  description="Shared defaults for this group. Blank values inherit the global fallback; a collection's explicit overrides take precedence. Save & Apply updates display settings without changing membership."
  busy={request.isPending || syncGroupRequest.isPending || applyRequest.isPending}
>
  <DataStatus
    label="group defaults"
    error={query.error}
    loading={query.isFetching}
    hasData={query.data !== undefined}
    onretry={() => query.refetch()}
  />
  <DataStatus
    label="global collection defaults"
    error={defaults.error}
    loading={defaults.isFetching}
    hasData={defaults.data !== undefined}
    onretry={() => defaults.refetch()}
  />
  {#if draft}
    <CollectionPolicyFields
      policy={draft}
      defaults={defaults.data}
      prefix="Group "
      plex={serverType === "plex"}
    />

    <label class="form-row">
      <input
        type="checkbox"
        checked={draft.sort_title_format === null}
        onchange={(event) => {
          if (draft) draft.sort_title_format = event.currentTarget.checked ? null : "";
        }}
      />
      Default sort title template
    </label>

    <label class="form-label">
      Group sort title template
      <input
        maxlength="200"
        value={draft.sort_title_format ?? ""}
        placeholder={defaults.data?.sort_title_format ?? ""}
        oninput={(event) => {
          if (draft) draft.sort_title_format = event.currentTarget.value;
        }}
      />
      <span class="hint">
        Use &#123;title&#125; and &#123;group&#125;. Empty disables formatting for this group.
      </span>
    </label>

    <label class="form-row">
      <input
        type="checkbox"
        checked={draft.summary_format === null}
        onchange={(event) => {
          if (draft) draft.summary_format = event.currentTarget.checked ? null : "";
        }}
      />
      Default summary template
    </label>

    <label class="form-label">
      Group summary template
      <input
        maxlength="500"
        value={draft.summary_format ?? ""}
        placeholder={defaults.data?.summary_format ?? ""}
        oninput={(event) => {
          if (draft) draft.summary_format = event.currentTarget.value;
        }}
      />
      <span class="hint">
        Tokens: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;, &#123;end_date&#125;,
        &#123;summary&#125;.
      </span>
    </label>

    <div class="seasonal-row form-wide">
      <label class="form-label">
        Active start (MM-DD)
        <input
          placeholder={defaults.data?.active_start_mmdd ?? ""}
          maxlength="5"
          value={draft.active_start_mmdd ?? ""}
          oninput={(e) => {
            if (draft) draft.active_start_mmdd = e.currentTarget.value.trim() || null;
          }}
        />
      </label>
      <label class="form-label">
        Active end (MM-DD)
        <input
          placeholder={defaults.data?.active_end_mmdd ?? ""}
          maxlength="5"
          value={draft.active_end_mmdd ?? ""}
          oninput={(e) => {
            if (draft) draft.active_end_mmdd = e.currentTarget.value.trim() || null;
          }}
        />
      </label>
    </div>

    {#if mediaType === "movie"}
      <div class="dynamic-discovery-section form-wide">
        <label class="form-row">
          <input
            type="checkbox"
            checked={draft.dynamic_tmdb !== null && (draft.dynamic_tmdb.enabled ?? false)}
            onchange={(e) => toggleDynamicTmdb(e.currentTarget.checked)}
          />
          Auto-discover TMDB franchise collections from library movies
        </label>

        {#if draft.dynamic_tmdb}
          <div class="options-col nested-options">
            {#if libraries.length > 0}
              <label class="form-label">
                Library
                <select bind:value={draft.dynamic_tmdb.library_id}>
                  {#each libraries as library (library.id)}
                    <option value={library.id}>{library.title}</option>
                  {/each}
                </select>
              </label>
            {/if}
            <CollectionDiscoveryFields config={draft.dynamic_tmdb} />
          </div>
        {/if}
      </div>
    {/if}

    <div class="form-row action-row form-wide">
      <button type="button" class="btn btn-secondary" onclick={() => void save()}>
        Save group defaults
      </button>
      <button type="button" class="btn btn-primary" onclick={() => void save(true)}
        >Save &amp; Apply to group</button
      >
      <button
        type="button"
        class="btn btn-ghost"
        disabled={syncGroupRequest.isPending}
        onclick={() => void syncGroup()}
      >
        <RefreshCw size={14} class={syncGroupRequest.isPending ? "animate-spin" : ""} />
        Sync Group Now
      </button>
    </div>
  {/if}
</DetailForm>

<style>
  .seasonal-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3);
    @media (max-width: 640px) {
      grid-template-columns: 1fr;
    }
  }

  .dynamic-discovery-section {
    border-top: var(--border-subtle);
    padding-top: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .nested-options {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
    padding-left: var(--space-4);
    border-left: var(--border-subtle);
    margin-top: var(--space-2);
  }

  .action-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding-top: var(--space-2);
  }
</style>
