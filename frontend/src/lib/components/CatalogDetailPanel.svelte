<script lang="ts">
  import Database from "@lucide/svelte/icons/database";
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import Music from "@lucide/svelte/icons/music";
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import {
    getPublicDatasetStatusOptions,
    getTmdbItemOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { ArtType, CatalogEntryDetail } from "../../generated/rest/types.gen";
  import {
    goToCatalogEntry,
    goToCollection,
    goToItem,
    type ArtSubTab,
    type ItemView,
  } from "../router/routes";
  import { settingsState } from "../stores/settingsState.svelte";
  import { CatalogDraft } from "../utils/catalogDraft";
  import { buildTmdbCollectionUrl } from "../utils/externalLinks";
  import { buildContributionIssueUrl } from "../utils/publicDataset";
  import type { ArtSlotTarget } from "../utils/tmdbItems";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import DataStatus from "./DataStatus.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import PasteArtButton from "./PasteArtButton.svelte";
  import StatusTab from "./StatusTab.svelte";
  import ThemePanel from "./ThemePanel.svelte";

  let {
    detail = null,
    view = { mode: "art", artSubTab: "poster", drillSeasonNum: null },
    members,
  }: { detail?: CatalogEntryDetail | null; view?: ItemView; members?: Snippet } = $props();
  let entry = $derived(detail?.draft ?? detail?.entry);
  let target = $derived(
    detail ? { media_type: detail.entry.media_type, entry_key: detail.entry_key } : null,
  );
  const draft = new CatalogDraft(() => target);
  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());
  const tmdbQuery = createQuery(() => ({
    ...getTmdbItemOptions({
      path: {
        media_type: entry?.media_type === "show" ? "show" : "movie",
        tmdb_id: entry?.tmdb_id ?? 0,
      },
    }),
    enabled:
      entry?.media_type === "show" &&
      !!entry.tmdb_id &&
      settingsState.current.tmdb_configured &&
      view.mode === "art" &&
      view.artSubTab === "seasons",
  }));
  let seasons = $derived(
    [
      ...new Set([
        ...(entry?.seasons ?? []).map((season) => season.season_num),
        ...(tmdbQuery.data?.seasons ?? []).map((season) => season.season_num),
      ]),
    ].sort((a, b) => a - b),
  );
  let artType = $derived<ArtType>(view.artSubTab === "seasons" ? "season_poster" : view.artSubTab);
  let slot = $derived<ArtSlotTarget | null>(
    target && entry
      ? {
          kind: "catalog",
          draft,
          mediaType: target.media_type,
          entryKey: target.entry_key,
          tmdbId: entry.tmdb_id,
          seasonNum: view.drillSeasonNum,
        }
      : null,
  );
  let contributionUrl = $derived(
    entry && datasetQuery.data?.repo_url
      ? buildContributionIssueUrl(datasetQuery.data.repo_url, entry)
      : null,
  );
  let artUrl = $derived(
    view.artSubTab === "background"
      ? entry?.background_url
      : view.artSubTab === "seasons"
        ? entry?.seasons?.find((season) => season.season_num === view.drillSeasonNum)?.poster_url
        : entry?.poster_url,
  );

  function openArt(tab: ArtSubTab, seasonNum: number | null = null) {
    if (target)
      goToCatalogEntry(target, { mode: "art", artSubTab: tab, drillSeasonNum: seasonNum });
  }
  function openLibrary() {
    if (!entry || !detail) return;
    if (detail.library_item_id && entry.media_type !== "collection")
      void goToItem({
        id: detail.library_item_id,
        title: entry.title,
        media_type: entry.media_type,
      });
    else if (detail.library_collection_id)
      goToCollection({ id: detail.library_collection_id, title: entry.title, media_type: "movie" });
  }
  function clearArt() {
    if (view.artSubTab === "seasons") {
      if (view.drillSeasonNum !== null)
        void draft.save({
          seasons: (entry?.seasons ?? []).filter(
            (season) => season.season_num !== view.drillSeasonNum,
          ),
        });
    } else
      void draft.save(
        view.artSubTab === "background" ? { background_url: null } : { poster_url: null },
      );
  }
</script>

<DetailPanelBase
  isEmpty={!entry}
  subjectKey={target ? `${target.media_type}:${target.entry_key}` : null}
  backgroundUrl={entry?.background_url}
  posterUrl={entry?.poster_url ?? null}
  title={entry?.title ?? ""}
  emptyMessage="Select an OvertureDB entry from the sidebar"
>
  {#snippet emptyIcon()}<Database size={64} />{/snippet}
  {#snippet posterIcon()}<Database size={48} />{/snippet}
  {#snippet meta()}
    {#if entry?.year}<span class="text-muted">{entry.year}</span>{/if}
    {#if detail?.draft}<span class="badge badge-warning">Draft</span>{/if}
  {/snippet}
  {#snippet badges()}
    {#if entry?.tmdb_id}
      <a
        class="btn btn-ghost btn-sm"
        href={entry.media_type === "collection"
          ? buildTmdbCollectionUrl(entry.tmdb_id)
          : `https://www.themoviedb.org/${entry.media_type === "show" ? "tv" : "movie"}/${entry.tmdb_id}`}
        target="_blank"
        rel="noreferrer">TMDB {entry.tmdb_id}</a
      >
    {/if}
    {#if detail?.library_item_id || detail?.library_collection_id}<button
        class="btn btn-ghost btn-sm"
        onclick={openLibrary}>Open in library</button
      >{/if}
    {#if contributionUrl}<a
        class="btn btn-ghost btn-sm"
        href={contributionUrl}
        target="_blank"
        rel="noreferrer">Contribute to OvertureDB</a
      >{/if}
    {#if detail?.draft}<button
        class="btn btn-ghost btn-sm"
        disabled={draft.busy}
        onclick={() => draft.discard()}>Discard draft</button
      >{/if}
  {/snippet}
  {#snippet tabs()}
    <StatusTab
      icon={Image}
      label="Art"
      clearLabel="Clear catalog art"
      active={view.mode === "art"}
      onselect={() => openArt("poster")}
    />
    <StatusTab
      icon={Music}
      label="Themes"
      active={view.mode === "themes"}
      onselect={() => {
        if (target)
          goToCatalogEntry(target, { mode: "themes", artSubTab: "poster", drillSeasonNum: null });
      }}
      clearLabel="Clear catalog theme"
      onclear={entry?.youtube_id_overturedb
        ? () => {
            void draft.save({ youtube_id_overturedb: null });
          }
        : null}
      clearDisabled={draft.busy}
    />
  {/snippet}
  {#snippet subtabs()}
    {#if view.mode === "art"}
      <StatusTab
        icon={Image}
        label="Poster"
        clearLabel="Clear catalog poster"
        active={view.artSubTab === "poster"}
        onselect={() => openArt("poster")}
      />
      <StatusTab
        icon={Image}
        label="Background"
        clearLabel="Clear catalog background"
        active={view.artSubTab === "background"}
        onselect={() => openArt("background")}
      />
      {#if entry?.media_type === "show"}<StatusTab
          icon={Layers}
          label="Seasons"
          clearLabel="Clear catalog season posters"
          active={view.artSubTab === "seasons"}
          onselect={() => openArt("seasons")}
        />{/if}
    {/if}
  {/snippet}
  {#snippet subtabActions()}
    {#if view.mode === "art" && (view.artSubTab !== "seasons" || view.drillSeasonNum !== null)}
      <PasteArtButton />
      {#if artUrl}<button class="btn btn-ghost btn-sm" disabled={draft.busy} onclick={clearArt}
          >Clear artwork</button
        >{/if}
    {/if}
  {/snippet}
  {#snippet content()}
    <div class="catalog-content">
      <p class="text-muted">Selections are saved as a local draft for contribution.</p>
      {#if view.mode === "themes"}
        {#if detail}<ThemePanel catalog={{ detail, draft }} />{/if}
      {:else if view.artSubTab === "seasons" && entry?.media_type === "show" && view.drillSeasonNum === null}
        <DataStatus
          label="TMDB seasons"
          error={tmdbQuery.error}
          loading={tmdbQuery.isFetching}
          hasData={tmdbQuery.data !== undefined}
          onretry={() => tmdbQuery.refetch()}
        />
        <div class="seasons">
          {#each seasons as number (number)}<button
              class="btn btn-secondary"
              onclick={() => openArt("seasons", number)}>Season {number}</button
            >{/each}
        </div>
        {#if !seasons.length}<p class="text-muted">
            No season posters. Configure TMDB to discover seasons.
          </p>{/if}
      {:else if slot && (view.artSubTab !== "seasons" || entry?.media_type === "show")}
        {#if view.artSubTab === "seasons"}<button
            class="btn btn-ghost self-start"
            onclick={() => openArt("seasons")}>All seasons</button
          >{/if}
        {#key `${slot.kind}:${target?.entry_key}:${artType}:${view.drillSeasonNum}`}<ArtSlotPanel
            {slot}
            {artType}
            item={null}
          />{/key}
      {/if}
      {#if members}{@render members()}{/if}
    </div>
  {/snippet}
</DetailPanelBase>

<style>
  .catalog-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .seasons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
