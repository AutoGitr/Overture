<script lang="ts">
  import Download from "@lucide/svelte/icons/download";
  import Folder from "@lucide/svelte/icons/folder";
  import Settings from "@lucide/svelte/icons/settings";
  import Trash from "@lucide/svelte/icons/trash";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import { goToGroup } from "../router/routes";
  import { setSectionView } from "../stores/sectionState.svelte";
  import { CollectionGroupEditor } from "../utils/collectionGroupEditor.svelte";
  import { countOf } from "../utils/plural";
  import CollectionConfigure from "./CollectionConfigure.svelte";
  import ConfigureNavigation, { type ConfigureSection } from "./ConfigureNavigation.svelte";
  import DataStatus from "./DataStatus.svelte";
  import DetailPanelBase from "./DetailPanelBase.svelte";
  import StatusTab from "./StatusTab.svelte";

  let {
    group,
    libraries,
  }: {
    group: string;
    libraries: LibrarySectionRead[];
  } = $props();
  setSectionView("collection-group");

  const editor = new CollectionGroupEditor(
    () => group,
    () => libraries,
  );
  const panelId = $props.id();
  const formId = `${panelId}-configure`;
  let set = $derived(editor.form.generator);
  let dimension = $derived(
    set
      ? (editor.form.dimensions.find((entry) => entry.dimension === set.dimension)?.label ??
          set.dimension)
      : null,
  );
  let sections = $derived<ConfigureSection[]>(
    set
      ? ["setup", "content", "members", "settings", "schedule"]
      : ["setup", "members", "settings", "schedule"],
  );
</script>

<DetailPanelBase
  emptyMessage="Select a group from the sidebar"
  isEmpty={false}
  subjectKey={`collection-group:${group}`}
  title={group}
  posterUrl={null}
  showPoster={false}
  tabs={configure}
>
  {#snippet emptyIcon()}<Folder size={64} />{/snippet}
  {#snippet posterIcon()}<Folder size={48} />{/snippet}
  {#snippet meta()}
    <span>{countOf(editor.members.length, "collection")}</span>
    {#if dimension}<span class="badge badge-accent">Set: {dimension}</span>{/if}
  {/snippet}
  {#snippet badges()}{/snippet}
  {#snippet recordActions()}
    <button
      type="button"
      class="tab-item"
      title="Export the group, its set and its collections as a file"
      aria-label="Export group"
      disabled={editor.busy}
      onclick={() => void editor.export()}
    >
      <Download size={16} />
    </button>
    <button
      type="button"
      class="tab-item danger"
      title="Delete group"
      aria-label="Delete group"
      disabled={editor.busy}
      onclick={() => void editor.delete()}
    >
      <Trash size={16} />
    </button>
  {/snippet}
  {#snippet sectionLinks()}
    <ConfigureNavigation
      {formId}
      configuring
      {sections}
      onopen={(target) => goToGroup(group, target)}
    />
  {/snippet}
  {#snippet content()}
    <DataStatus
      label="group"
      error={editor.saved.error}
      loading={editor.saved.isFetching}
      hasData={editor.saved.data !== undefined}
      onretry={() => editor.saved.refetch()}
    />
    {#if editor.saved.data}
      <CollectionConfigure {editor} {formId} {libraries} />
    {/if}
  {/snippet}
</DetailPanelBase>

{#snippet configure()}
  <StatusTab icon={Settings} label="Configure" active />
{/snippet}
