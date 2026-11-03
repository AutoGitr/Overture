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

<div style:height="148px">
  <VirtualList width={300} {itemCount} itemSize={74} {scrollOffset}>
    {#snippet row(index: number, style: string)}
      <div {style}>Row {index}</div>
    {/snippet}
  </VirtualList>
</div>
