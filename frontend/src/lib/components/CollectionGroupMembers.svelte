<script lang="ts">
  import type { CollectionRead } from "../../generated/rest/types.gen";
  import { goToCollection } from "../router/routes";
  import { countOf } from "../utils/plural";
  import DetailForm from "./DetailForm.svelte";

  let {
    members,
    set,
  }: {
    members: readonly CollectionRead[];
    /** The group is a set, which creates its collections when it syncs. */
    set: boolean;
  } = $props();
</script>

<DetailForm
  collapsible
  title="Members"
  busy={false}
  description={members.length
    ? `${countOf(members.length, "collection")} in the group.`
    : set
      ? "None yet: sync the group to create its collections."
      : "None yet: choose this group in a collection's Setup."}
>
  {#if members.length}
    <ul class="members" aria-label="Collections in the group">
      {#each members as row (row.id)}
        <li>
          <button type="button" class="member" onclick={() => goToCollection(row)}>
            <span class="truncate">{row.title}</span>
            <span class="hint">{countOf(row.child_count, "title")}</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</DetailForm>

<style>
  .members {
    display: grid;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .member {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    text-align: left;
  }

  .member:hover {
    background: var(--bg-hover);
  }
</style>
