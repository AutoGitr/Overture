<!-- Downloads running outside an Assets run, such as choices made in an item. -->
<script lang="ts">
  import DownloadQueue from "./DownloadQueue.svelte";
</script>

<DownloadQueue lane="art" label="Art downloads" />
<DownloadQueue lane="theme" label="Theme downloads" />
