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
    /** Stands in for the poster when there is none to show. */
    posterIcon: Snippet;
    title: string;
    /** Beside the title, such as the year. */
    meta?: Snippet;
    /** `IdBadge` links. */
    badges: Snippet;
    /** The section tabs, such as Collection, Art and Themes. */
    tabs: Snippet;
    /** Record actions share a fixed position beside the mode tabs. */
    recordActions?: Snippet;
    /** The active section's category tabs. */
    subtabs?: Snippet;
    subtabLabel?: string;
    showSubtabs?: boolean;
    /** Actions beside the category tabs. */
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
    posterIcon,
    title,
    meta,
    badges,
    tabs,
    recordActions,
    subtabs,
    subtabLabel = "Art categories",
    showSubtabs = true,
    subtabActions,
    content,
  }: Props = $props();
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
    <div class="detail-header">
      <svelte:element
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
      </svelte:element>

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

        <div class="detail-sections">
          <div class="detail-tab-row">
            <div class="mode-tabs tab-bar" role="tablist" aria-label="Detail modes">
              {@render tabs()}
            </div>
            {#if recordActions}
              <div class="record-actions tab-bar" role="group" aria-label="Record actions">
                {@render recordActions()}
              </div>
            {/if}
          </div>
          {#if subtabs && showSubtabs}
            <div class="detail-tab-row">
              <div class="detail-subtabs tab-bar" role="tablist" aria-label={subtabLabel}>
                {@render subtabs()}
              </div>
              {@render subtabActions?.()}
            </div>
          {/if}
        </div>
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

  /* -- Header: stacked and centred by default ----------------------------- */
  /* Element sizes are identical in both layouts; only the arrangement changes. */
  .detail-header {
    /* Cross-axis alignment for every header row: centred here, start when wide. */
    --header-align: center;

    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-4);
    padding: var(--space-4) var(--gutter) 0;
    flex-shrink: 0;
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

  .detail-heading,
  .detail-sections {
    display: flex;
    flex-direction: column;
    align-items: var(--header-align);
    gap: var(--space-3);
    max-width: 100%;
  }

  /* -- Poster: same width as a poster candidate card ---------------------- */
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
    font-family: var(--font-mono);
    color: var(--text-tertiary);
  }

  .detail-title {
    font-size: var(--text-3xl);
    font-weight: 700;
    margin: 0;
    line-height: 1.15;
    text-wrap: balance;
  }

  /* -- ID badges ---------------------------------------------------------- */
  .id-badges {
    display: flex;
    justify-content: var(--header-align);
    gap: var(--space-2);
    flex-wrap: wrap;
  }

  /* -- Mode tabs, art sub-tabs (+ paste button) --------------------------- */
  .detail-tab-row {
    /* Tab button height; bars add 8px (padding + border) around it. */
    --tab-height: 36px;

    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: var(--header-align);
    gap: var(--space-2);
    max-width: 100%;
  }

  .tab-bar {
    margin: 0;
    max-width: 100%;
    /* Each bar scrolls sideways rather than wrapping its buttons. */
    overflow-x: auto;
    scrollbar-width: none;
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

  /* -- Side by side: sidebar pinned (not hideable) and room for both ------- */
  /* Poster left; title and links at its top, the tab rows at its bottom. */
  @media (min-width: 769px) and (not ((max-height: 500px) and (pointer: coarse))) {
    @container detail-panel (min-width: 640px) {
      .detail-header {
        --header-align: flex-start;

        flex-direction: row;
        align-items: stretch;
        gap: var(--space-5);
      }

      .detail-poster {
        align-self: flex-start;
      }

      .detail-header-main {
        justify-content: space-between;
        width: auto;
        flex: 1;
        text-align: start;
      }
    }
  }

  /* Candidates go two per row here, so the poster takes one column's width. */
  @container detail-panel (max-width: 480px) {
    .detail-poster {
      width: calc((100% - var(--space-3)) / 2);
    }
  }
</style>
