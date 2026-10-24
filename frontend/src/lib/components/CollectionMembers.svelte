<script lang="ts">
  import type { MediaItemRead, TmdbItemResult } from "../../generated/rest/types.gen";
  import { goToCatalogEntry, goToItem } from "../router/routes";
  import { itemArtDisplayUrl, remotePosterUrl } from "../utils/artDisplay";
  import PosterCard from "./PosterCard.svelte";
  import ImageGrid from "./ImageGrid.svelte";

  let {
    members,
    catalog = false,
  }: { members: (MediaItemRead | TmdbItemResult)[]; catalog?: boolean } = $props();

  function open(member: MediaItemRead | TmdbItemResult) {
    if (catalog && "catalog_entry_key" in member && member.catalog_entry_key) {
      goToCatalogEntry({ media_type: member.media_type, entry_key: member.catalog_entry_key });
      return;
    }
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

<section aria-label="Collection members">
  <ImageGrid title="Members" count={members.length}>
    {#if members.length === 0}<p class="text-muted">No members found.</p>{/if}
    {#each members as member ("id" in member ? member.id : member.tmdb_id)}
      <PosterCard
        title={`${member.title}${member.year ? ` (${member.year})` : ""}`}
        src={"id" in member ? itemArtDisplayUrl(member, "poster") : remotePosterUrl(member)}
        onselect={() => open(member)}
        meta={"id" in member || member.existing_item_id ? "In library" : null}
      />
    {/each}
  </ImageGrid>
</section>
