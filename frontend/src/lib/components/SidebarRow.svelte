<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Sparkles from "@lucide/svelte/icons/sparkles";
  import type {
    CatalogEntryRow,
    CollectionRead,
    MediaItemRead,
    TmdbCollectionResult,
    TmdbItemResult,
  } from "../../generated/rest/types.gen";
  import {
    collectionArtDisplayUrl,
    collectionPosterOriginalUrl,
    itemArtDisplayUrl,
    itemPosterOriginalUrl,
    remotePosterUrl,
  } from "../utils/artDisplay";
  import { MEDIA_ICONS, type MediaIcon } from "../utils/mediaIcons";
  import { catalogStatus, type StatusTone } from "../utils/sidebarDomain";
  import SidebarAssetBadges from "./SidebarAssetBadges.svelte";
  import FallbackImage from "./FallbackImage.svelte";

  let {
    style,
    index,
    active,
    catalogEntry = null,
    item = null,
    collection = null,
    tmdbResult = null,
    hideTheme = false,
    artStatus = null,
    themeStatus = null,
    onSelect,
    onOpenArt = () => {},
    onOpenThemes = () => {},
  }: {
    style: string;
    index: number;
    active: boolean;
    catalogEntry?: CatalogEntryRow | null;
    item?: MediaItemRead | null;
    collection?: CollectionRead | null;
    /** A TMDB search result, not yet stored. */
    tmdbResult?: TmdbItemResult | TmdbCollectionResult | null;
    hideTheme?: boolean;
    artStatus?: StatusTone | null;
    themeStatus?: StatusTone | null;
    onSelect: () => void | Promise<void>;
    onOpenArt?: () => void | Promise<void>;
    onOpenThemes?: () => void | Promise<void>;
  } = $props();

  let catalogTones = $derived(catalogEntry ? catalogStatus(catalogEntry) : null);

  interface Row {
    title: string;
    selectLabel: string;
    meta: string | number | null;
    unmonitored: boolean;
    icon: MediaIcon;
    src: string | null;
    /** Where the poster opens full size, with what its link says. */
    link: { href: string; label: string; title: string } | null;
  }

  /** Where the poster opens full size, for every kind of row alike. */
  function posterLink(title: string, href: string | null): Row["link"] {
    return href
      ? { href, label: `Open poster for ${title} in new tab`, title: "Open poster in new tab" }
      : null;
  }

  /** What every kind of row shows, so one layout renders them all. */
  let row = $derived.by((): Row | null => {
    if (catalogEntry) {
      return {
        title: catalogEntry.title,
        selectLabel: `Select ${catalogEntry.title}`,
        meta: catalogEntry.year,
        unmonitored: false,
        icon: MEDIA_ICONS[catalogEntry.media_type],
        src: remotePosterUrl(catalogEntry),
        link: posterLink(catalogEntry.title, catalogEntry.poster_url),
      };
    }
    if (item) {
      const src = itemArtDisplayUrl(item, "poster");
      return {
        title: item.title,
        selectLabel: `Select ${item.title}`,
        meta: item.year,
        unmonitored: !item.monitored,
        icon: MEDIA_ICONS[item.media_type],
        src,
        link: src ? posterLink(item.title, itemPosterOriginalUrl(item)) : null,
      };
    }
    if (tmdbResult) {
      const isCollection = tmdbResult.kind === "collection";
      const title = isCollection ? `Collection: ${tmdbResult.title}` : tmdbResult.title;
      return {
        title,
        selectLabel: isCollection ? `Open ${title}` : `Select ${title}`,
        meta: tmdbResult.kind === "item" ? tmdbResult.year : null,
        unmonitored: false,
        icon: MEDIA_ICONS[isCollection ? "collection" : tmdbResult.media_type],
        src: remotePosterUrl(tmdbResult),
        link: null,
      };
    }
    if (collection) {
      return {
        title: collection.title,
        selectLabel: `Select collection ${collection.title}`,
        meta:
          collection.media_types.length > 1
            ? `${collection.child_count} items, movies and shows`
            : `${collection.child_count} items`,
        unmonitored: !collection.monitored,
        icon: MEDIA_ICONS.collection,
        src: collectionArtDisplayUrl(collection, "poster"),
        link: posterLink(collection.title, collectionPosterOriginalUrl(collection)),
      };
    }
    return null;
  });
</script>

{#if row}
  <div {style} class={["sidebar-item", { active, alt: index % 2 !== 0 }]}>
    {#snippet placeholder()}
      <div class="item-poster-placeholder">
        <row.icon size={16} />
      </div>
    {/snippet}

    <!-- The virtual list mounts only rows near the viewport, so a row's image
         is wanted now: lazy loading would only add another visibility check. -->
    {#snippet poster()}
      <FallbackImage src={row.src} alt="" loading="eager" loadDelayMs={100} {placeholder} />
    {/snippet}

    {#if row.link}
      <a
        href={row.link.href}
        target="_blank"
        rel="noreferrer"
        class="item-poster"
        aria-label={row.link.label}
        title={row.link.title}
      >
        {@render poster()}
      </a>
    {:else}
      <div class="item-poster">
        {@render poster()}
      </div>
    {/if}

    <button type="button" class="sidebar-item-main" aria-label={row.selectLabel} onclick={onSelect}>
      <div class="item-info">
        <span class="item-title truncate">{row.title}</span>
        <div class="item-meta">
          {#if row.meta}
            <span>{row.meta}</span>
          {/if}
          {#if catalogEntry?.has_draft}<span class="badge badge-warning">Draft</span>{/if}
          {#if collection?.kind === "smart"}
            <span class="smart" title="Smart collection"
              ><Sparkles size={12} aria-hidden="true" /><span class="sr-only">Smart collection</span
              ></span
            >
          {/if}
          {#if row.unmonitored}
            <EyeOff size={12} class="item-unmonitored" />
          {/if}
        </div>
      </div>
    </button>

    <SidebarAssetBadges
      title={row.title}
      artStatus={catalogTones?.art ?? artStatus}
      themeStatus={catalogTones?.theme ?? themeStatus}
      hideTheme={hideTheme || (!!collection && settingsState.current.media_server === "emby")}
      onart={onOpenArt}
      onthemes={onOpenThemes}
    />
  </div>
{/if}

<style>
  .sidebar-item {
    position: relative;
    isolation: isolate;
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-2) var(--space-3);
    text-align: left;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background-color 0.12s ease;
  }

  .sidebar-item::before {
    content: "";
    position: absolute;
    left: 3px;
    top: 50%;
    transform: translateY(-50%) scaleY(0);
    width: 3px;
    height: 36px;
    border-radius: var(--radius-full);
    background: var(--accent);
    opacity: 0;
    pointer-events: none;
    transition:
      transform 0.15s cubic-bezier(0.16, 1, 0.3, 1),
      opacity 0.15s ease;
  }

  .sidebar-item.active::before {
    transform: translateY(-50%) scaleY(1);
    opacity: 1;
  }

  .sidebar-item-main {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    height: 100%;
    padding: 0;
    text-align: left;
    background: transparent;
    border: 0;
    cursor: pointer;
  }

  .sidebar-item-main::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: 1;
  }

  .sidebar-item-main:focus-visible::after {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .sidebar-item.alt {
    background: var(--row-alt-bg);
  }

  .sidebar-item:hover {
    background: var(--bg-hover);
  }

  .sidebar-item.active {
    background: var(--bg-tertiary);
  }

  .item-poster {
    flex-shrink: 0;
    width: 46px;
    height: 69px;
    overflow: hidden;
    background: var(--bg-tertiary);
    border-radius: 4px;
    display: block;
    text-decoration: none;
  }

  a.item-poster {
    position: relative;
    z-index: 2;
    cursor: pointer;
  }

  a.item-poster:hover {
    opacity: 0.8;
  }

  a.item-poster:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .item-poster-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    color: var(--text-tertiary);
  }

  .item-info {
    display: flex;
    flex: 1;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .item-title {
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-weight: 500;
  }

  .item-meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-tertiary);
    font-size: var(--text-xs);
  }

  .smart {
    display: inline-flex;
    color: var(--accent);
  }

  .sidebar-item :global(.item-unmonitored) {
    color: var(--text-tertiary);
  }
</style>
