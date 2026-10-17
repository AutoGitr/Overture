<script lang="ts">
  import VirtualList from "../../lib/components/VirtualList.svelte";

  let {
    itemCount,
    scrollOffset = 0,
  }: {
    itemCount: number;
    scrollOffset?: number;
  } = $props();
</script>

<VirtualList width={300} maxHeight="148px" {itemCount} itemSize={74} {scrollOffset}>
  {#snippet row(index: number, style: string)}
    <div {style}>Row {index}</div>
  {/snippet}
</VirtualList>
