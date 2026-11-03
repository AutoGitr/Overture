<script lang="ts">
  import { notificationState } from "../stores/notificationState.svelte";
  import ConfirmDialog from "./ConfirmDialog.svelte";
  import ToastRegion from "./ToastRegion.svelte";
</script>

{#if notificationState.confirmRequest}
  <ConfirmDialog request={notificationState.confirmRequest} />
{/if}

<ToastRegion root />
