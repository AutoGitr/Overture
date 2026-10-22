<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { ThemeSearchResultItem } from "../utils/themeSearch";
  import { formatThemeDuration, youtubeEmbedUrl } from "../utils/themeSearch";

  interface Props {
    results: ThemeSearchResultItem[];
    currentYoutubeId?: string | null;
    busyVideoId?: string | null;
    disabled?: boolean;
    selectLabel?: (video: ThemeSearchResultItem) => string;
    onSelect: (video: ThemeSearchResultItem) => void | Promise<void>;
  }

  function defaultSelectLabel(video: ThemeSearchResultItem): string {
    return currentYoutubeId === video.id ? "Overwrite" : "Select";
  }

  function getBadgeClass(variant?: string): string {
    if (!variant) return "badge-muted";
    return variant.startsWith("badge-") ? variant : `badge-${variant}`;
  }

  function isSelected(video: ThemeSearchResultItem): boolean {
    return (
      currentYoutubeId === video.id ||
      Boolean(video.badges?.some((b) => b.label === "Currently Selected"))
    );
  }

  function isOvertureDb(video: ThemeSearchResultItem): boolean {
    return Boolean(video.badges?.some((b) => b.label === "OvertureDB"));
  }

  function isThemerrDb(video: ThemeSearchResultItem): boolean {
    return Boolean(video.badges?.some((b) => b.label === "ThemerrDB"));
  }

  let {
    results,
    currentYoutubeId = null,
    busyVideoId = null,
    disabled = false,
    selectLabel = defaultSelectLabel,
    onSelect,
  }: Props = $props();
</script>

{#if results.length > 0}
  <div class="theme-results">
    {#each results as video (video.id)}
      <div
        class={[
          "theme-card card",
          {
            "is-selected": isSelected(video),
            "is-overturedb": isOvertureDb(video),
            "is-themerrdb": isThemerrDb(video),
          },
        ]}
      >
        <div class="theme-card-preview">
          <iframe
            src={youtubeEmbedUrl(video.id)}
            title={video.title}
            frameborder="0"
            allow="accelerometer; encrypted-media; gyroscope"
            allowfullscreen
            loading="lazy"
          ></iframe>
        </div>
        <div class="theme-card-info">
          <div class="theme-card-header">
            {#if video.badges && video.badges.length > 0}
              <div class="theme-card-badges">
                {#each video.badges as badge (badge.label)}
                  <span class="badge {getBadgeClass(badge.variant)}">
                    {#if badge.label === "Currently Selected"}
                      <Check size={11} strokeWidth={2.5} />
                    {/if}
                    {badge.label}
                  </span>
                {/each}
              </div>
            {/if}
            <span class="theme-card-title truncate">{video.title}</span>
          </div>

          <div class="theme-card-footer">
            <div class="theme-card-meta">
              {#if video.channel}
                <span class="theme-card-channel">{video.channel}</span>
              {/if}
              {#if video.duration}
                <span class="badge badge-muted">
                  {formatThemeDuration(video.duration)}
                </span>
              {/if}
            </div>

            <button
              class={[
                "btn btn-sm",
                {
                  "btn-primary": !currentYoutubeId || currentYoutubeId !== video.id,
                  "btn-secondary": currentYoutubeId === video.id,
                },
              ]}
              onclick={() => onSelect(video)}
              disabled={disabled || busyVideoId === video.id}
            >
              {#if busyVideoId === video.id}
                <LoaderCircle size={12} class="animate-spin" />
              {:else}
                {selectLabel(video)}
              {/if}
            </button>
          </div>
        </div>
      </div>
    {/each}
  </div>
{/if}

<style>
  .theme-results {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 480px), 1fr));
    gap: var(--space-4);
  }

  .theme-card {
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }

  .theme-card.is-selected {
    border-color: oklch(from var(--success) l c h / 0.45);
    box-shadow: 0 0 0 1px oklch(from var(--success) l c h / 0.15);
  }

  .theme-card.is-overturedb:not(.is-selected) {
    border-color: color-mix(in oklch, var(--accent) 45%, var(--surface-glass-border));
  }

  .theme-card.is-themerrdb:not(.is-selected):not(.is-overturedb) {
    border-color: oklch(from var(--warning) l c h / 0.4);
  }

  .theme-card-preview {
    aspect-ratio: 16/9;
    background: var(--bg-tertiary);
    width: 100%;
    min-height: 250px;
  }

  .theme-card-preview iframe {
    width: 100%;
    height: 100%;
    border: none;
    display: block;
  }

  .theme-card-info {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
    background: var(--bg-secondary);
  }

  .theme-card-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  .theme-card-badges {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
  }

  .theme-card-title {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-primary);
    min-width: 0;
  }

  .theme-card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .theme-card-meta {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    min-width: 0;
    flex-wrap: wrap;
  }

  .theme-card-channel {
    color: var(--text-secondary);
    font-size: var(--text-xs);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 220px;
  }

  .theme-card-footer .btn {
    flex-shrink: 0;
    align-self: center;
  }

  @media (max-width: 480px) {
    .theme-results {
      grid-template-columns: 1fr;
    }

    .theme-card-preview {
      min-height: 200px;
    }
  }
</style>
