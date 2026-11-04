<script lang="ts">
  import type { Snippet } from "svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import FallbackImage from "./FallbackImage.svelte";

  interface Props {
    /** Show the empty/placeholder state instead of the full panel. */
    isEmpty: boolean;
    /**
     * What the panel shows (an item, a TMDB title, a collection). Its images
     * are new elements for each subject: a reused image would keep showing
     * the previous subject's art until the new art loads.
     */
    subjectKey: string | number | null;
    backgroundUrl?: string | null;
    /** If set, wraps the poster in an <a> pointing here. */
    posterHref?: string | null;
    posterLinkTitle?: string | null;
    /** Optional summary text rendered below the header row. */
    summary?: string | null;
    /** What to pick from the sidebar, shown while nothing is open. */
    emptyMessage: string;
    emptyIcon: Snippet;
    posterUrl: string | null;
    showPoster?: boolean;
    /** Stands in for the poster when there is none to show. */
    posterIcon: Snippet;
    title: string;
    /** Beside the title, such as the year. */
    meta?: Snippet;
    /** `IdBadge` links. */
    badges: Snippet;
    /** The mode tabs, such as Configure, Art and Themes; without them the panel has no tab rows. */
    tabs?: Snippet;
    /** Record actions share a fixed position beside the mode tabs. */
    recordActions?: Snippet;
    /** The art category tabs, shown in every mode so the row never changes. */
    subtabs?: Snippet;
    /** Links to the sections of a form, beside the art tabs. */
    sectionLinks?: Snippet;
    /** Actions beside the art tabs. */
    subtabActions?: Snippet;
    content: Snippet;
  }

  let {
    isEmpty,
    subjectKey,
    backgroundUrl,
    posterHref,
    posterLinkTitle,
    summary,
    emptyMessage,
    emptyIcon,
    posterUrl,
    showPoster = true,
    posterIcon,
    title,
    meta,
    badges,
    tabs,
    recordActions,
    subtabs,
    sectionLinks,
    subtabActions,
    content,
  }: Props = $props();

  function navigateTabs(event: KeyboardEvent) {
    if (!(event.currentTarget instanceof HTMLElement) || !(event.target instanceof HTMLElement))
      return;
    if (!event.target.closest('[role="tab"]')) return;
    const tabs = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="tab"]')];
    const index = tabs.findIndex((tab) => tab === event.target);
    if (index === -1) return;
    const next =
      event.key === "ArrowRight"
        ? (index + 1) % tabs.length
        : event.key === "ArrowLeft"
          ? (index + tabs.length - 1) % tabs.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? tabs.length - 1
              : null;
    if (next === null) return;
    event.preventDefault();
    tabs[next]?.focus();
    tabs[next]?.click();
  }
</script>

<main class="detail-panel">
  {#if isEmpty}
    <div class="detail-empty">
      <div class="empty-icon">
        {@render emptyIcon()}
      </div>
      <p>{emptyMessage}</p>
    </div>
  {:else}
    {#if backgroundUrl && settingsState.show_background_image}
      <div class="detail-background">
        {#key subjectKey}
          <img src={backgroundUrl} alt="" fetchpriority="low" decoding="async" />
        {/key}
      </div>
    {/if}

    <!-- The whole panel scrolls, so the header gives its height back to the
         content (art grids, theme results) as soon as you scroll. -->
    <div class={["detail-header", { "no-poster": !showPoster }]}>
      {#if showPoster}<svelte:element
          this={posterHref ? "a" : "div"}
          class={["detail-poster", { "is-link": !!posterHref }]}
          href={posterHref ?? null}
          target={posterHref ? "_blank" : null}
          rel={posterHref ? "noopener noreferrer" : null}
          title={posterLinkTitle ?? null}
          aria-label={posterLinkTitle ?? null}
        >
          <!-- An image that fails to load (a file gone from disk) shows the
             placeholder. The title is the heading beside it, so the image has
             no alt text for a browser to draw in its place while it loads. -->
          {#key subjectKey}
            <FallbackImage
              src={posterUrl}
              alt=""
              loading="eager"
              fetchpriority="high"
              placeholder={posterPlaceholder}
            />
          {/key}
        </svelte:element>{/if}

      <div class="detail-header-main">
        <div class="detail-heading">
          <div class="title-row">
            <h2 class="detail-title">{title}</h2>
            {#if meta}<div class="detail-meta">{@render meta()}</div>{/if}
          </div>
          <div class="id-badges">
            {@render badges()}
          </div>
          {#if summary}
            <p class="detail-summary">{summary}</p>
          {/if}
        </div>

        {#if tabs}<div class="detail-sections">
            <div class="detail-tab-row tab-bar">
              <div
                class="mode-tabs"
                role="tablist"
                tabindex="-1"
                aria-label="Detail modes"
                onkeydown={navigateTabs}
              >
                {@render tabs()}
              </div>
              {#if recordActions}
                <div class="record-actions" role="group" aria-label="Record actions">
                  {@render recordActions()}
                </div>
              {/if}
            </div>
            <div class="detail-tab-row tab-bar">
              {#if sectionLinks}
                <nav class="section-links" aria-label="Configure sections">
                  {@render sectionLinks()}
                </nav>
              {/if}
              <div
                class="detail-subtabs"
                role="tablist"
                tabindex="-1"
                aria-label="Art categories"
                onkeydown={navigateTabs}
              >
                {@render subtabs?.()}
              </div>
              {#if subtabActions}
                <div class="section-actions" role="group" aria-label="Section actions">
                  {@render subtabActions()}
                </div>
              {/if}
            </div>
          </div>{/if}
      </div>
    </div>

    <div class="detail-content">
      {@render content()}
    </div>
  {/if}
</main>

{#snippet posterPlaceholder()}
  <div class="poster-placeholder">
    {@render posterIcon()}
  </div>
{/snippet}

<style>
  /* -- Panel shell -------------------------------------------------------- */
  /* Art grids and the header poster share breakpoints on this panel's width. */
  .detail-panel {
    container: detail-panel / inline-size;
    flex: 2;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
    overflow-y: auto;
    background: var(--bg-root);
    position: relative;
    z-index: 0;
  }

  .detail-background {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 420px;
    opacity: 0.7;
    z-index: -1;
  }

  .detail-background img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    object-position: center 25%;
  }

  /* Light scrim: enough behind the title and tabs for legibility, no more.
     The first layer fades the image into the panel background, which a
     mask-image would do at a higher compositing cost. */
  .detail-background::after {
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(to bottom, transparent 35%, var(--bg-root)),
      linear-gradient(
        to bottom,
        oklch(from var(--bg-root) l c h / 0.35),
        oklch(from var(--bg-root) l c h / 0.1) 45%,
        oklch(from var(--bg-root) l c h / 0.45)
      ),
      linear-gradient(
        to right,
        oklch(from var(--bg-root) l c h / 0.45),
        oklch(from var(--bg-root) l c h / 0) 60%
      );
  }

  /* -- Empty state -------------------------------------------------------- */
  .detail-empty {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-4);
    color: var(--text-tertiary);
  }

  .empty-icon {
    opacity: 0.2;
  }

  /* -- Header: stacked and centred until a desktop panel has room beside it */
  .detail-header {
    --header-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    padding: var(--space-4) var(--gutter) 0;
    flex-shrink: 0;
  }

  .detail-header.no-poster {
    --header-align: flex-start;
    align-items: flex-start;
  }

  .detail-header-main {
    display: flex;
    flex-direction: column;
    align-items: var(--header-align);
    gap: var(--space-4);
    width: 100%;
    min-width: 0;
    text-align: center;
  }

  .detail-header.no-poster .detail-header-main {
    text-align: start;
  }

  .detail-heading,
  .detail-sections {
    display: flex;
    flex-direction: column;
    align-items: var(--header-align);
    max-width: 100%;
  }

  .detail-heading {
    gap: var(--space-3);
  }

  .detail-sections {
    gap: var(--space-2);
  }

  /* -- Poster ------------------------------------------------------------- */
  .detail-poster {
    flex-shrink: 0;
    width: var(--art-poster-width);
    aspect-ratio: 2 / 3;
    border-radius: var(--radius-md);
    overflow: hidden;
    background: var(--bg-tertiary);
    box-shadow: var(--shadow-md);
  }

  .detail-poster.is-link {
    display: block;
  }

  /* The image FallbackImage renders. */
  .detail-poster :global(img) {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .poster-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-tertiary);
  }

  /* -- Title row ---------------------------------------------------------- */
  .title-row {
    display: flex;
    align-items: baseline;
    justify-content: var(--header-align);
    gap: var(--space-1) var(--space-3);
    flex-wrap: wrap;
  }

  .detail-meta {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    font-size: var(--text-lg);
    font-variant-numeric: tabular-nums;
    color: var(--text-tertiary);
  }

  .detail-title {
    font-size: clamp(var(--text-xl), 5cqi, var(--text-3xl));
    font-weight: 700;
    margin: 0;
    line-height: 1.15;
    text-wrap: balance;
    overflow-wrap: anywhere;
  }

  /* -- ID badges ---------------------------------------------------------- */
  .id-badges {
    display: flex;
    justify-content: var(--header-align);
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  .id-badges:empty {
    display: none;
  }

  /* -- Mode tabs, art sub-tabs (+ paste button) --------------------------- */
  .detail-tab-row {
    /* Tab button height; bars add 8px (padding + border) around it. */
    --tab-height: 36px;

    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: var(--header-align);
    gap: var(--space-1);
    max-width: 100%;
  }

  /* A bar wraps onto another line rather than hiding buttons off its edge. */
  .tab-bar {
    margin: 0;
    overflow: visible;
  }

  .mode-tabs,
  .detail-subtabs,
  .section-links,
  .record-actions,
  .section-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: var(--header-align);
    gap: var(--space-1);
  }

  .section-links {
    padding-right: var(--space-1);
    border-right: var(--border-subtle);
  }

  .record-actions :global(.tab-item.danger) {
    color: var(--danger);
  }

  .tab-bar :global(.tab-item:disabled) {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* -- Summary ------------------------------------------------------------ */
  .detail-summary {
    max-width: 80ch;
    overflow-wrap: anywhere;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    line-height: 1.6;
  }

  /* -- Content area ------------------------------------------------------- */
  .detail-content {
    flex: 1 0 auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding: var(--space-4) var(--gutter) calc(var(--space-6) + var(--safe-area-bottom));
  }

  /* Two-column poster grids (<= 480px panel): match one column's width. */
  @container detail-panel (max-width: 480px) {
    .detail-poster {
      width: calc((100% - var(--space-3)) / 2);
    }
  }

  /* Side-by-side header once the desktop panel has room for poster + tabs. */
  @media (min-width: 769px) and (not ((max-height: 500px) and (pointer: coarse))) {
    @container detail-panel (min-width: 640px) {
      .detail-header {
        --header-align: flex-start;
        flex-direction: row;
        align-items: flex-start;
        gap: var(--space-5);
      }

      .detail-header-main {
        flex: 1;
        align-self: stretch;
        justify-content: space-between;
        text-align: start;
      }
    }
  }
</style>
