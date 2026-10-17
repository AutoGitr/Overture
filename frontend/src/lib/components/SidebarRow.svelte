<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import EyeOff from "@lucide/svelte/icons/eye-off";
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import Music from "@lucide/svelte/icons/music";
  import type {
    CollectionRead,
    MediaItemRead,
    TmdbCollectionResult,
    TmdbItemResult,
  } from "../../generated/rest/types.gen";
  import {
    collectionImageUrl,
    itemArtDisplayUrl,
    itemPosterOriginalUrl,
    remotePosterUrl,
  } from "../utils/artDisplay";
  import type { StatusTone } from "../utils/sidebarDomain";
  import FallbackImage from "./FallbackImage.svelte";

  let {
    style,
    index,
    active,
    item = null,
    collection = null,
    tmdbResult = null,
    artStatus = null,
    themeStatus = null,
    onSelect,
    onOpenArt = () => {},
    onOpenThemes = () => {},
  }: {
    style: string;
    index: number;
    active: boolean;
    item?: MediaItemRead | null;
    collection?: CollectionRead | null;
    /** A TMDB search result, not yet stored. */
    tmdbResult?: TmdbItemResult | TmdbCollectionResult | null;
    artStatus?: StatusTone | null;
    themeStatus?: StatusTone | null;
    onSelect: () => void | Promise<void>;
    onOpenArt?: () => void | Promise<void>;
    onOpenThemes?: () => void | Promise<void>;
  } = $props();

  // The virtual list mounts only rows near the viewport, so a row's image is
  // wanted now: lazy loading would only add another visibility check.
  const rowImage = { loading: "eager", loadDelayMs: 100 } as const;
</script>

{#if item}
  {@const posterSrc = itemArtDisplayUrl(item, "poster")}
  <div {style} class="sidebar-item" class:active class:alt={index % 2 !== 0}>
    {#snippet placeholder()}
      <div class="item-poster-placeholder">
        {#if item.media_type === "movie"}
          <Clapperboard size={16} />
        {:else}
          <MonitorPlay size={16} />
        {/if}
      </div>
    {/snippet}

    {#if posterSrc}
      <a
        href={itemPosterOriginalUrl(item)}
        target="_blank"
        rel="noreferrer"
        class="item-poster"
        aria-label={`Open poster for ${item.title} in new tab`}
        title="Open poster in new tab"
      >
        <FallbackImage src={posterSrc} alt="" {...rowImage} {placeholder} />
      </a>
    {:else}
      <div class="item-poster">
        <FallbackImage src={null} alt="" {...rowImage} {placeholder} />
      </div>
    {/if}

    <button
      type="button"
      class="sidebar-item-main"
      aria-label={`Select ${item.title}`}
      onclick={onSelect}
    >
      <div class="item-info">
        <span class="item-title truncate">{item.title}</span>
        <div class="item-meta">
          {#if item.year}
            <span>{item.year}</span>
          {/if}
          {#if !item.monitored}
            <EyeOff size={12} class="item-unmonitored" />
          {/if}
        </div>
      </div>
    </button>

    <div class="item-badges">
      <button
        type="button"
        class="item-badge"
        aria-label={`Open art for ${item.title}`}
        title="Art"
        data-status={artStatus}
        onclick={onOpenArt}
      >
        <Image size={18} />
      </button>

      <button
        type="button"
        class="item-badge"
        aria-label={`Open themes for ${item.title}`}
        title="Theme Music"
        data-status={themeStatus}
        onclick={onOpenThemes}
      >
        <Music size={18} />
      </button>
    </div>
  </div>
{:else if tmdbResult}
  {@const isCollection = tmdbResult.kind === "collection"}
  {@const label = isCollection ? `Collection: ${tmdbResult.title}` : tmdbResult.title}
  <div {style} class="sidebar-item" class:active class:alt={index % 2 !== 0}>
    {#snippet placeholder()}
      <div class="item-poster-placeholder">
        {#if isCollection}
          <Layers size={16} />
        {:else if tmdbResult.kind === "item" && tmdbResult.media_type === "show"}
          <MonitorPlay size={16} />
        {:else}
          <Clapperboard size={16} />
        {/if}
      </div>
    {/snippet}

    <div class="item-poster">
      <FallbackImage src={remotePosterUrl(tmdbResult)} alt="" {...rowImage} {placeholder} />
    </div>

    <button
      type="button"
      class="sidebar-item-main"
      aria-label={isCollection ? `Open ${label}` : `Select ${label}`}
      onclick={onSelect}
    >
      <div class="item-info">
        <span class="item-title truncate">{label}</span>
        <div class="item-meta">
          {#if tmdbResult.kind === "item" && tmdbResult.year}
            <span>{tmdbResult.year}</span>
          {/if}
        </div>
      </div>
    </button>
  </div>
{:else if collection}
  <div {style} class="sidebar-item" class:active class:alt={index % 2 !== 0}>
    {#snippet placeholder()}
      <div class="item-poster-placeholder">
        <Layers size={16} />
      </div>
    {/snippet}

    {#if collection.thumb_url}
      <a
        href={collection.thumb_url}
        target="_blank"
        rel="noreferrer"
        class="item-poster"
        aria-label={`Open thumbnail for ${collection.title} in new tab`}
        title="Open thumbnail in new tab"
      >
        <FallbackImage
          src={collectionImageUrl(collection.thumb_url)}
          alt=""
          {...rowImage}
          {placeholder}
        />
      </a>
    {:else}
      <div class="item-poster">
        <FallbackImage src={null} alt="" {...rowImage} {placeholder} />
      </div>
    {/if}

    <button
      type="button"
      class="sidebar-item-main"
      aria-label={`Select collection ${collection.title}`}
      onclick={onSelect}
    >
      <div class="item-info">
        <span class="item-title truncate">{collection.title}</span>
        <div class="item-meta">
          <span>{collection.child_count} items</span>
          {#if !collection.monitored}
            <EyeOff size={12} class="item-unmonitored" />
          {/if}
        </div>
      </div>
    </button>

    <div class="item-badges">
      <span class="item-badge" data-status={themeStatus} title="Theme Music">
        <Music size={18} />
      </span>
    </div>
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
    background: var(--bg-hover) !important;
  }

  .sidebar-item.active {
    background: var(--bg-tertiary) !important;
    border-color: var(--accent);
    box-shadow: inset 3px 0 0 var(--accent);
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

  .item-badges {
    position: relative;
    z-index: 2;
    display: flex;
    flex-shrink: 0;
    flex-direction: column;
    gap: var(--space-1);
    pointer-events: none;
  }

  /* Status is carried by one tone (data-status, app.css): a full-strength icon
     and outline on the panel's own surface, so no tint dilutes the contrast. */
  .item-badge {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    color: var(--tone, var(--text-tertiary));
    background: var(--bg-primary);
    border: 1.5px solid var(--tone, var(--text-tertiary));
    border-radius: var(--radius-sm);
    cursor: pointer;
  }

  button.item-badge {
    pointer-events: auto;
  }

  button.item-badge:hover {
    background: oklch(from var(--tone, var(--text-tertiary)) l c h / 0.18);
  }

  button.item-badge:focus-visible {
    outline: 2px solid var(--tone, var(--text-tertiary));
    outline-offset: 1px;
  }

  :global(.item-unmonitored) {
    color: var(--text-tertiary);
  }
</style>
