<script lang="ts">
  import type { CollectionMember, TmdbItemResult } from "../../generated/rest/types.gen";
  import { goToItem } from "../router/routes";

  let { members }: { members: (CollectionMember | TmdbItemResult)[] } = $props();

  function open(member: CollectionMember | TmdbItemResult) {
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
  {#each members as member ("id" in member ? member.id : member.tmdb_id)}
    <button class="member" onclick={() => open(member)}>
      <span>{member.title}{member.year ? ` (${member.year})` : ""}</span>
      {#if "id" in member || member.existing_item_id}<span class="badge badge-muted"
          >In library</span
        >{/if}
    </button>
  {/each}
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
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    text-align: left;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
  }
  .member:hover {
    background: var(--bg-hover);
  }
  .member .badge {
    flex-shrink: 0;
  }
</style>
