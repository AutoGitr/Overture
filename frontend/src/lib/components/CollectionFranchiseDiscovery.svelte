<script lang="ts">
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createMutation } from "@tanstack/svelte-query";
  import {
    saveCollectionGroupPolicyMutation,
    syncCollectionGroupMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import DetailForm from "./DetailForm.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { splitIds } from "../utils/collectionBuilders";
  import { errorMessage } from "../utils/errors";
  import { goToCollectionsList, openSidebarGroup } from "../router/routes";

  let {
    libraries = [],
  }: {
    libraries: LibrarySectionRead[];
  } = $props();

  const feedback = createNotifier();
  const savePolicyRequest = createMutation(() => saveCollectionGroupPolicyMutation());
  const syncGroupRequest = createMutation(() => syncCollectionGroupMutation());

  let selectedLibraryId = $state<string | null>(null);
  let libraryId = $derived(selectedLibraryId ?? libraries[0]?.id ?? "");
  let groupName = $state("Franchises");
  let minimumItems = $state(2);
  let stripPrefix = $state("The ");
  let stripSuffix = $state(" Collection");
  let sortTitleFormat = $state("+1_{title}");
  let autoExclude = $state(true);
  let excludeIdsText = $state("");

  let busy = $derived(savePolicyRequest.isPending || syncGroupRequest.isPending);

  async function discoverAndCreate() {
    if (busy) return;
    const cleanGroup = groupName.trim();
    if (!cleanGroup) {
      feedback.error("Please enter a group name for the franchise collections.");
      return;
    }
    if (!libraryId) {
      feedback.error("Please select a movie library.");
      return;
    }

    try {
      await savePolicyRequest.mutateAsync({
        query: { name: cleanGroup, media_type: "movie" },
        body: {
          minimum_items: minimumItems,
          sort_title_format: sortTitleFormat.trim() || null,
          dynamic_tmdb: {
            enabled: true,
            library_id: libraryId,
            strip_prefix: stripPrefix,
            strip_suffix: stripSuffix,
            auto_exclude_from_other_collections: autoExclude,
            exclude_tmdb_ids: splitIds(excludeIdsText),
          },
        },
      });

      await syncGroupRequest.mutateAsync({
        query: { name: cleanGroup, media_type: "movie" },
      });

      feedback.success(`Franchise discovery complete for group "${cleanGroup}".`);

      openSidebarGroup(cleanGroup);
      goToCollectionsList("movie");
    } catch (err) {
      feedback.error(errorMessage(err, "Franchise discovery failed"));
    }
  }
</script>

<DetailForm
  title="Auto-discover TMDB Movie Franchises"
  description="Automatically scan your movie library and create individual collections for every franchise meeting your threshold."
  {busy}
>
  <div class="form-label">
    <label for="discovery-library">Movie library</label>
    <select
      id="discovery-library"
      value={libraryId}
      onchange={(e) => (selectedLibraryId = e.currentTarget.value)}
      disabled={busy}
    >
      {#each libraries as library (library.id)}
        <option value={library.id}>{library.title}</option>
      {/each}
    </select>
  </div>

  <label class="form-label">
    Collection group
    <input maxlength="100" bind:value={groupName} disabled={busy} placeholder="Franchises" />
    <span class="hint">All discovered franchise collections will share this group.</span>
  </label>

  <label class="form-label">
    Minimum movies in library
    <input type="number" min="1" max="50" bind:value={minimumItems} disabled={busy} />
    <span class="hint"
      >Only create collections for franchises where you own at least this many movies.</span
    >
  </label>

  <div class="seasonal-row">
    <label class="form-label">
      Strip title prefix
      <input maxlength="50" bind:value={stripPrefix} disabled={busy} placeholder="The " />
      <span class="hint">e.g. "The Matrix Collection" &rarr; "Matrix"</span>
    </label>
    <label class="form-label">
      Strip title suffix
      <input maxlength="50" bind:value={stripSuffix} disabled={busy} placeholder=" Collection" />
      <span class="hint">Removes trailing " Collection"</span>
    </label>
  </div>

  <label class="form-label">
    Sort title template
    <input
      maxlength="100"
      bind:value={sortTitleFormat}
      disabled={busy}
      placeholder="+1_&#123;title&#125;"
    />
    <span class="hint"
      >Applied to all discovered collections (use &#123;title&#125; and &#123;group&#125;).</span
    >
  </label>

  <label class="form-row form-wide">
    <input type="checkbox" bind:checked={autoExclude} disabled={busy} />
    Auto-exclude movies that already belong to other collections
  </label>

  <label class="form-label form-wide">
    Exclude TMDB franchise IDs
    <input placeholder="e.g. 10, 86311" bind:value={excludeIdsText} disabled={busy} />
    <span class="hint">Comma-separated TMDB collection IDs to skip.</span>
  </label>

  <div class="form-wide action-bar">
    <button
      type="button"
      class="btn btn-secondary"
      disabled={busy}
      onclick={() => void discoverAndCreate()}
    >
      {#if busy}
        <RefreshCw size={14} class="spin" />
        Discovering franchises...
      {:else}
        <Sparkles size={14} />
        Discover &amp; Create Collections
      {/if}
    </button>
  </div>
</DetailForm>

<style>
  .seasonal-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
  }
  @media (max-width: 640px) {
    .seasonal-row {
      grid-template-columns: 1fr;
    }
  }
  .action-bar {
    margin-top: var(--space-2);
  }
</style>
