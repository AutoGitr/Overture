<script lang="ts">
  import DatabaseBackup from "@lucide/svelte/icons/database-backup";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { createMutation } from "@tanstack/svelte-query";
  import { createBackupMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { backupState } from "../stores/jobStates.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { delayedFlag } from "../utils/delayedFlag.svelte";
  import { errorMessage } from "../utils/errors";
  import CardColumn from "../components/CardColumn.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import BackupList from "../components/backup/BackupList.svelte";
  import BackupScheduleCard from "../components/backup/BackupScheduleCard.svelte";
  import BackupSection from "../components/backup/BackupSection.svelte";

  const feedback = createNotifier();
  const backupNowRequest = createMutation(() => createBackupMutation());
  let backingUp = $derived(backupNowRequest.isPending || backupState.running);
  const showBackingUp = delayedFlag(() => backingUp);

  async function backupNow() {
    if (backingUp) return;
    feedback.clear();
    try {
      const { filename, removed } = await backupNowRequest.mutateAsync({});
      const pruned =
        removed.length > 0
          ? ` Retention removed ${removed.length === 1 ? removed[0] : `${removed.length} older backups`}.`
          : "";
      feedback.success(`Saved ${filename}.${pruned}`, { title: "Backup complete" });
    } catch (e) {
      feedback.error(errorMessage(e, "Backup failed"));
    }
  }
</script>

<PopupShell title="Backup" onclose={() => uiState.closePopup()}>
  <CardColumn>
    <BackupSection icon={DatabaseBackup} title="Manual backup">
      <p class="hint">
        Every backup applies the retention below, so older backups it no longer keeps are removed.
      </p>
      <div class="actions-row backup-now-row">
        <button
          class="btn btn-primary"
          onclick={backupNow}
          disabled={backingUp}
          aria-busy={backingUp}
        >
          {#if showBackingUp.current}
            <LoaderCircle size={15} class="animate-spin" />
            Backing up...
          {:else}
            <DatabaseBackup size={15} />
            Back up now
          {/if}
        </button>
      </div>
    </BackupSection>
    <BackupScheduleCard />
    <BackupList />
  </CardColumn>
  {#snippet footer()}
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Close</button>
  {/snippet}
</PopupShell>

<style>
  .backup-now-row .btn {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
</style>
