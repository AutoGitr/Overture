<script lang="ts" module>
  /** A managed collection a run can choose by itself. */
  export interface ChoosableCollection {
    id: number;
    title: string;
    /** The group it belongs to, Ungrouped when it has none. */
    group: string;
  }
</script>

<script lang="ts">
  import { toggleCollectionGroup, type CollectionChoice } from "../utils/popupSelection";
  import Checklist from "./Checklist.svelte";
  import CheckboxList from "./CheckboxList.svelte";

  let {
    groups,
    choice,
    onchange,
    collections,
    collectionIds = [],
    oncollectionschange,
  }: {
    /** The groups a run can choose. */
    groups: string[];
    /** What is chosen; left out while another choice, such as the sidebar's, applies. */
    choice?: CollectionChoice;
    onchange: (choice: CollectionChoice) => void;
    /** The collections a run can also choose one by one; left out where it cannot. */
    collections?: ChoosableCollection[];
    collectionIds?: number[];
    oncollectionschange?: (ids: number[]) => void;
  } = $props();

  let all = $derived(!!choice?.all);
  let chosenGroups = $derived<ReadonlySet<string>>(new Set(all ? groups : (choice?.groups ?? [])));
  let chosenIds = $derived<ReadonlySet<number>>(new Set(collectionIds));
  let filter = $state("");
  /** Collections a chosen group already covers show as chosen, and stay so. */
  let options = $derived(
    (collections ?? [])
      .filter((row) => row.title.toLowerCase().includes(filter.trim().toLowerCase()))
      .map((row) => {
        const covered = chosenGroups.has(row.group);
        return {
          value: String(row.id),
          label: row.title,
          disabled: covered,
          title: covered ? `Chosen with ${row.group}` : undefined,
        };
      }),
  );
  let selected = $derived(
    (collections ?? [])
      .filter((row) => chosenGroups.has(row.group) || chosenIds.has(row.id))
      .map((row) => String(row.id)),
  );
  /** How many collections are chosen apart from their groups. */
  let chosenApart = $derived(
    (collections ?? []).filter((row) => chosenIds.has(row.id) && !chosenGroups.has(row.group))
      .length,
  );
</script>

<div class="collection-checklist">
  <Checklist
    label="Collections"
    groups={[
      {
        key: "groups",
        label: "Groups",
        options: groups.map((group) => ({
          id: group,
          label: group,
          checked: chosenGroups.has(group),
        })),
      },
    ]}
    allSelected={all}
    ontoggle={(_key, group) =>
      onchange(toggleCollectionGroup(choice ?? { all: false, groups: [] }, group, groups))}
    ontoggleall={(checked) => onchange({ all: checked, groups: [] })}
  />
  {#if collections?.length && oncollectionschange}
    <details>
      <summary class="caps-label">
        Specific collections{chosenApart ? ` (${chosenApart})` : ""}
      </summary>
      <div class="specific">
        <input
          type="search"
          class="filter"
          placeholder="Filter collections"
          aria-label="Filter collections"
          bind:value={filter}
        />
        <CheckboxList
          {options}
          {selected}
          ontoggle={(value) => {
            const id = Number(value);
            oncollectionschange(
              chosenIds.has(id)
                ? collectionIds.filter((chosen) => chosen !== id)
                : [...collectionIds, id],
            );
          }}
        />
      </div>
    </details>
  {/if}
</div>

<style>
  .collection-checklist {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  summary {
    cursor: pointer;
  }

  .specific {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-2);
  }

  .filter {
    max-width: 20rem;
  }
</style>
