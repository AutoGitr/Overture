<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import type { MediaItemRead, TmdbItemResult } from "../../generated/rest/types.gen";
  import { goToItem } from "../router/routes";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import FallbackImage from "./FallbackImage.svelte";
  import ImageGrid from "./ImageGrid.svelte";

  let { members }: { members: (MediaItemRead | TmdbItemResult)[] } = $props();

  function open(member: MediaItemRead | TmdbItemResult) {
    const id = "id" in member ? member.id : member.existing_item_id;
    if (id) void goToItem({ id, title: member.title, media_type: member.media_type });
    else if (member.tmdb_id)
      void goToItem({
        tmdb_id: member.tmdb_id,
        title: member.title,
        media_type: member.media_type,
      });
  }
</script>

<section class="members" aria-label="Collection members">
  <h3>Members</h3>
  {#if members.length === 0}<p class="text-muted">No members found.</p>{/if}
  <ImageGrid>
    {#each members as member ("id" in member ? member.id : member.tmdb_id)}
      <button class="member card card-interactive" onclick={() => open(member)}>
        <div class="member-poster">
          {#snippet placeholder()}<Layers size={32} />{/snippet}
          <FallbackImage
            src={"id" in member ? itemArtDisplayUrl(member, "poster") : remotePosterUrl(member)}
            alt=""
            {placeholder}
          />
        </div>
        <span class="member-title">{member.title}{member.year ? ` (${member.year})` : ""}</span>
        {#if "id" in member || member.existing_item_id}<span class="badge badge-muted"
            >In library</span
          >{/if}
      </button>
    {/each}
  </ImageGrid>
</section>

<style>
  .members {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .members h3 {
    font-size: var(--text-sm);
  }
  .member {
    display: flex;
    flex-direction: column;
    text-align: left;
    padding: 0;
    overflow: hidden;
  }
  .member-poster {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    aspect-ratio: var(--art-aspect);
    background: var(--bg-tertiary);
    color: var(--text-tertiary);
  }
  .member-title {
    padding: var(--space-3);
  }
  .member .badge {
    margin: 0 var(--space-3) var(--space-3);
  }
</style>
