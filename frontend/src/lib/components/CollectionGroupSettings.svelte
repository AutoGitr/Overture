<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    getCollectionGroupPolicyOptions,
    saveCollectionGroupPolicyMutation,
    syncCollectionGroupMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionGroupPolicyOutput,
    LibrarySectionRead,
    MediaType,
    ServerType,
  } from "../../generated/rest/types.gen";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DataStatus from "./DataStatus.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { splitIds } from "../utils/collectionBuilders";
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
  let open = $state(false);
  const query = createQuery(() => ({
    ...getCollectionGroupPolicyOptions({ query: { name: group, media_type: mediaType } }),
    enabled: open,
  }));
  const request = createMutation(() => saveCollectionGroupPolicyMutation());
  const syncGroupRequest = createMutation(() => syncCollectionGroupMutation());
  const feedback = createNotifier();

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

  async function save() {
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
      feedback.success("Group defaults saved. Collections use them on their next save or sync.");
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

<details class="form-wide" ontoggle={(event) => (open = event.currentTarget.open)}>
  <summary>Defaults for group: {group}</summary>
  <p class="hint">
    Blank values inherit global defaults. Collection overrides take precedence. Changes apply on the
    next save or sync.
  </p>
  <DataStatus
    label="group defaults"
    error={query.error}
    loading={query.isFetching}
    hasData={query.data !== undefined}
    onretry={() => query.refetch()}
  />
  {#if draft}
    <fieldset class="options-col" disabled={request.isPending || syncGroupRequest.isPending}>
      <legend>Group defaults</legend>
      <CollectionPolicyFields bind:policy={draft} prefix="Group " plex={serverType === "plex"} />

      <label class="form-row">
        <input
          type="checkbox"
          checked={draft.sort_title_format === null}
          onchange={(event) => {
            if (draft) draft.sort_title_format = event.currentTarget.checked ? null : "";
          }}
        />
        Inherit global sort title template
      </label>

      {#if draft.sort_title_format !== null}
        <label class="form-label">
          Group sort title template
          <input maxlength="200" bind:value={draft.sort_title_format} />
          <span class="hint">
            Use &#123;title&#125; and &#123;group&#125;. Empty disables formatting for this group.
          </span>
        </label>
      {/if}

      <label class="form-row">
        <input
          type="checkbox"
          checked={draft.summary_format === null}
          onchange={(event) => {
            if (draft) draft.summary_format = event.currentTarget.checked ? null : "";
          }}
        />
        Inherit global summary template
      </label>

      {#if draft.summary_format !== null}
        <label class="form-label">
          Group summary template
          <input maxlength="500" bind:value={draft.summary_format} />
          <span class="hint">
            Tokens: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;,
            &#123;end_date&#125;, &#123;summary&#125;.
          </span>
        </label>
      {/if}

      <div class="seasonal-row">
        <label class="form-label">
          Active start (MM-DD)
          <input
            placeholder="12-15"
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
            placeholder="01-05"
            maxlength="5"
            value={draft.active_end_mmdd ?? ""}
            oninput={(e) => {
              if (draft) draft.active_end_mmdd = e.currentTarget.value.trim() || null;
            }}
          />
        </label>
      </div>

      {#if mediaType === "movie"}
        <div class="dynamic-discovery-section">
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
              <div class="affix-grid">
                <label class="form-label">
                  Strip prefix
                  <input
                    placeholder="e.g. The "
                    maxlength="50"
                    bind:value={draft.dynamic_tmdb.strip_prefix}
                  />
                </label>
                <label class="form-label">
                  Strip suffix
                  <input
                    placeholder="e.g.  Collection"
                    maxlength="50"
                    bind:value={draft.dynamic_tmdb.strip_suffix}
                  />
                </label>
              </div>
              <label class="form-row">
                <input
                  type="checkbox"
                  bind:checked={draft.dynamic_tmdb.auto_exclude_from_other_collections}
                />
                Auto-exclude franchise movies from other collections
              </label>
              <label class="form-label">
                Exclude TMDB franchise IDs
                <input
                  placeholder="e.g. 10, 86311"
                  value={draft.dynamic_tmdb.exclude_tmdb_ids.join(", ")}
                  oninput={(e) => {
                    if (draft?.dynamic_tmdb) {
                      draft.dynamic_tmdb.exclude_tmdb_ids = splitIds(e.currentTarget.value);
                    }
                  }}
                />
                <span class="hint">Comma-separated TMDB collection IDs to skip.</span>
              </label>
            </div>
          {/if}
        </div>
      {/if}

      <div class="form-row action-row">
        <button type="button" class="btn btn-secondary" onclick={() => void save()}>
          Save group defaults
        </button>
        <button
          type="button"
          class="btn btn-ghost"
          disabled={syncGroupRequest.isPending}
          onclick={() => void syncGroup()}
        >
          <RefreshCw size={14} class={syncGroupRequest.isPending ? "spin" : ""} />
          Sync Group Now
        </button>
      </div>
    </fieldset>
  {/if}
</details>

<style>
  .seasonal-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3, 0.75rem);
  }

  .dynamic-discovery-section {
    border-top: 1px solid var(--border-color, #333);
    padding-top: var(--space-3, 0.75rem);
    display: flex;
    flex-direction: column;
    gap: var(--space-2, 0.5rem);
  }

  .nested-options {
    padding-left: var(--space-4, 1rem);
    border-left: 2px solid var(--border-color, #444);
    margin-top: var(--space-2, 0.5rem);
  }

  .affix-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3, 0.75rem);
  }

  .action-row {
    display: flex;
    align-items: center;
    gap: var(--space-3, 0.75rem);
    padding-top: var(--space-2, 0.5rem);
  }

  :global(.spin) {
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }
</style>
