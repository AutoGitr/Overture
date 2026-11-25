<script lang="ts">
  import Download from "@lucide/svelte/icons/download";
  import FileUp from "@lucide/svelte/icons/file-up";
  import LibraryBig from "@lucide/svelte/icons/library-big";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    exportCollectionPresetMutation,
    listCollectionPresetsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionPresetFileInput,
    PresetExport,
    PresetListing,
  } from "../../generated/rest/types.gen";
  import CollectionChecklist from "../components/CollectionChecklist.svelte";
  import ContributeIssueLink from "../components/ContributeIssueLink.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import PopupTabs from "../components/PopupTabs.svelte";
  import PresetImport from "../components/PresetImport.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { choosableCollections, collectionGroupNames } from "../utils/collectionGroups.svelte";
  import { errorMessage } from "../utils/errors";
  import { allLibraries } from "../utils/libraries.svelte";

  type Tab = "gallery" | "file" | "export";
  const TABS = [
    { id: "gallery", label: "OvertureDB", icon: LibraryBig },
    { id: "file", label: "Import file", icon: FileUp },
    { id: "export", label: "Export", icon: Download },
  ] as const;

  let tab = $state<Tab>("gallery");
  const libraries = allLibraries();
  const gallery = createQuery(() => ({
    ...listCollectionPresetsOptions(),
    enabled: tab === "gallery",
  }));
  /** The preset being added from the gallery. */
  let picked = $state<PresetListing | null>(null);

  /** A file read from disk, and why it could not be read. */
  let imported = $state.raw<CollectionPresetFileInput | null>(null);
  let fileError = $state("");

  async function readFile(file: File) {
    imported = null;
    fileError = "";
    try {
      imported = JSON.parse(await file.text()) as CollectionPresetFileInput;
    } catch {
      fileError = `${file.name} is not a collections file exported from Overture`;
    }
  }

  const groups = collectionGroupNames(() => tab === "export");
  const collections = choosableCollections(() => tab === "export");
  let exportGroups = $state<string[]>([]);
  let exportIds = $state<number[]>([]);
  let exported = $state.raw<PresetExport | null>(null);
  const feedback = createNotifier();
  const exportRequest = createMutation(() => exportCollectionPresetMutation());

  async function exportChosen() {
    feedback.clear();
    try {
      exported = await exportRequest.mutateAsync({
        body: {
          groups: exportGroups.length ? exportGroups : null,
          collection_ids: exportIds.length ? exportIds : null,
        },
      });
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to export the collections"));
      return;
    }
    if (!exported.file) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(exported.file, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "overture-collections.json";
    link.click();
    // Following the link resolves the blob URL at once, so the download keeps
    // the file after the URL is revoked.
    URL.revokeObjectURL(url);
  }
</script>

<PopupShell title="Collection presets" size="wide" onclose={() => uiState.closePopup()}>
  {#snippet tabs()}
    <PopupTabs
      tabs={TABS}
      active={tab}
      label="Preset sources"
      idPrefix="presets"
      onselect={(chosen) => (tab = chosen)}
    />
  {/snippet}

  {#snippet about()}
    Adding a preset copies its collections and sets into your libraries; they are yours to
    change. When OvertureDB publishes a newer version, you choose what of it to take.
  {/snippet}

  <DataStatus
    label="libraries"
    error={libraries.error}
    loading={libraries.isFetching}
    hasData={libraries.data !== undefined}
    onretry={() => libraries.refetch()}
  />

  <div
    role="tabpanel"
    id="presets-panel-gallery"
    aria-labelledby="presets-tab-gallery"
    hidden={tab !== "gallery"}
  >
    <DataStatus
      label="presets"
      error={gallery.error}
      loading={gallery.isFetching}
      hasData={gallery.data !== undefined}
      onretry={() => gallery.refetch()}
    />
    {#if gallery.data?.error}
      <p class="hint">{gallery.data.error}</p>
    {/if}
    {#if picked?.file}
      <h3>{picked.preset?.title}</h3>
      <PresetImport file={picked.file} libraries={libraries.data ?? []} />
      <button type="button" class="btn btn-secondary" onclick={() => (picked = null)}
        >Back to presets</button
      >
    {:else}
      <ul class="presets" aria-label="OvertureDB presets">
        {#each gallery.data?.presets ?? [] as listing (listing.id)}
          <li class="preset">
            {#if listing.preview_url}
              <img src={listing.preview_url} alt="" loading="lazy" />
            {/if}
            <div class="preset-text">
              <strong>{listing.preset?.title ?? listing.id}</strong>
              {#if listing.preset}
                <span class="badge badge-muted">{listing.preset.category}</span>
                <p>{listing.preset.description}</p>
              {/if}
              {#if listing.problem}
                <p class="hint">{listing.problem}</p>
              {/if}
              {#each listing.unavailable ?? [] as integration (integration)}
                <span class="badge badge-warning">Needs {integration}</span>
              {/each}
              {#if listing.changes?.length}
                <span class="badge badge-accent">Newer version</span>
                <ul class="changes" aria-label="What the newer version changes">
                  {#each listing.changes as change (change)}<li>{change}</li>{/each}
                </ul>
              {:else if listing.added_at}
                <span class="badge badge-muted">Added</span>
              {/if}
            </div>
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              disabled={!listing.file}
              onclick={() => (picked = listing)}
              >{listing.changes?.length ? "Update…" : listing.added_at ? "Add again…" : "Add…"}</button
            >
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div
    role="tabpanel"
    id="presets-panel-file"
    aria-labelledby="presets-tab-file"
    hidden={tab !== "file"}
  >
    <label class="form-label"
      >Collections file
      <input
        type="file"
        accept="application/json,.json"
        onchange={(event) => {
          const file = event.currentTarget.files?.[0];
          if (file) void readFile(file);
        }}
      /></label
    >
    {#if fileError}<p class="hint">{fileError}</p>{/if}
    {#if imported}
      <PresetImport file={imported} libraries={libraries.data ?? []} />
    {/if}
  </div>

  <div
    role="tabpanel"
    id="presets-panel-export"
    aria-labelledby="presets-tab-export"
    hidden={tab !== "export"}
  >
    <p class="hint">
      Export groups, with their sets, and collections as a file another install can add, or
      contribute it to OvertureDB as a preset.
    </p>
    <CollectionChecklist
      groups={groups()}
      choice={{ all: false, groups: exportGroups }}
      onchange={(choice) => (exportGroups = choice.all ? groups() : choice.groups)}
      collections={collections()}
      collectionIds={exportIds}
      oncollectionschange={(ids) => (exportIds = ids)}
    />
    {#if exported}
      {#each exported.refused ?? [] as refusal (refusal.title)}
        <p class="hint">Left out {refusal.title}: {refusal.reason}</p>
      {/each}
      {#each exported.warnings ?? [] as warning (warning)}
        <p class="hint">{warning}</p>
      {/each}
      {#if exported.file}
        <p class="contribute">
          Contribute it to OvertureDB <ContributeIssueLink issue={exported.issue} />
        </p>
      {/if}
    {/if}
  </div>

  {#snippet footer()}
    <button type="button" class="btn btn-secondary" onclick={() => uiState.closePopup()}
      >Close</button
    >
    {#if tab === "export"}
      <button
        type="button"
        class="btn btn-primary"
        disabled={exportRequest.isPending || (!exportGroups.length && !exportIds.length)}
        onclick={exportChosen}>Export</button
      >
    {/if}
  {/snippet}
</PopupShell>

<style>
  .presets {
    display: grid;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .preset {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: start;
    gap: var(--space-3);
  }

  .preset img {
    width: 3rem;
    aspect-ratio: 2 / 3;
    object-fit: cover;
    border-radius: var(--radius-sm);
  }

  .preset-text p {
    margin: var(--space-1) 0;
  }

  .changes {
    margin: var(--space-1) 0 0;
    padding-inline-start: var(--space-4);
  }

  .form-label {
    display: grid;
    gap: var(--space-2);
    margin-block: var(--space-3);
  }

  .contribute {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
</style>
