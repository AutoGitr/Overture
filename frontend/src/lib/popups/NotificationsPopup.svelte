<script lang="ts">
  import Bell from "@lucide/svelte/icons/bell";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import {
    getNotificationsOptions,
    sendTestNotificationMutation,
    updateNotificationsMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { NotificationRuleRead, NotifyCompleted } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import DataStatus from "../components/DataStatus.svelte";
  import PendingButton from "../components/PendingButton.svelte";
  import PopupShell from "../components/PopupShell.svelte";

  const COMPLETED: readonly (readonly [NotifyCompleted, string])[] = [
    ["never", "Never"],
    ["always", "Always"],
    ["changes", "With changes"],
    ["errors", "With errors"],
  ];

  const queryClient = useQueryClient();
  const settingsQuery = createQuery(() => getNotificationsOptions());
  const saveRequest = createMutation(() => updateNotificationsMutation());
  const testRequest = createMutation(() => sendTestNotificationMutation());
  const feedback = createNotifier();

  /** The form's rules, seeded once from the server. */
  let rules = $state<NotificationRuleRead[] | null>(null);
  $effect(() => {
    if (settingsQuery.data && rules === null) {
      rules = settingsQuery.data.rules.map((rule) => ({ ...rule }));
    }
  });
  let service = $derived(settingsQuery.data?.service_label ?? null);
  let busy = $derived(saveRequest.isPending || testRequest.isPending);

  async function save() {
    if (!rules || busy) return;
    feedback.clear();
    try {
      const saved = await saveRequest.mutateAsync({
        body: { rules: rules.map(({ label: _label, ...rule }) => rule) },
      });
      queryClient.setQueryData(getNotificationsOptions().queryKey, saved);
      uiState.closePopup();
      feedback.success("Notification settings saved.");
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to save the notification settings"));
    }
  }

  async function sendTest() {
    if (busy) return;
    feedback.clear();
    try {
      await testRequest.mutateAsync({});
      feedback.success(`Test notification sent to ${service}.`);
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to send the test notification"));
    }
  }
</script>

<PopupShell title="Notifications" size="form" onclose={() => uiState.closePopup()}>
  {#snippet icon()}
    <Bell size={18} />
  {/snippet}
  <DataStatus
    label="notification settings"
    error={settingsQuery.error}
    loading={settingsQuery.isFetching}
    hasData={settingsQuery.data !== undefined}
    onretry={() => settingsQuery.refetch()}
  />
  {#if settingsQuery.data}
    <p class="hint">
      {#if service}
        Notifications go to {service} at the address <code>NOTIFY_URL</code> names.
      {:else}
        Set <code>NOTIFY_URL</code> to a Discord, Slack, Telegram, Gotify, ntfy or Apprise address
        to send notifications. These rules apply once it is set.
      {/if}
    </p>
  {/if}
  {#if rules}
    <fieldset class="rules" disabled={busy} aria-label="When each kind of run sends a notification">
      {#each rules as rule (rule.kind)}
        <section class="rule" aria-label={rule.label}>
          <h4 class="caps-label">{rule.label}</h4>
          <div class="rule-fields">
            <label class="form-row">
              <input type="checkbox" bind:checked={rule.failed} />
              <span>Failed</span>
            </label>
            <label class="form-row">
              <input type="checkbox" bind:checked={rule.stopped} />
              <span>Stopped</span>
            </label>
            <label class="form-row">
              <span>Completed</span>
              <select class="select-compact" bind:value={rule.completed}>
                {#each COMPLETED as [value, label] (value)}
                  <option {value}>{label}</option>
                {/each}
              </select>
            </label>
            <label class="form-row">
              <input type="checkbox" bind:checked={rule.scheduled_only} />
              <span>Scheduled runs only</span>
            </label>
          </div>
        </section>
      {/each}
    </fieldset>
    <p class="hint">
      With changes: the run added, changed, removed or downloaded something, or found a mismatch.
      With errors: some of its titles failed. Scheduled runs only leaves out runs started by hand.
    </p>
  {/if}
  {#snippet footer()}
    <PendingButton
      class="btn btn-secondary actions-start"
      pending={testRequest.isPending}
      pendingLabel="Sending..."
      disabled={busy || !service}
      onclick={sendTest}>Send test notification</PendingButton
    >
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Cancel</button>
    <PendingButton
      class="btn btn-primary"
      pending={saveRequest.isPending}
      pendingLabel="Saving..."
      disabled={busy || !rules}
      onclick={save}>Save</PendingButton
    >
  {/snippet}
</PopupShell>

<style>
  .rules {
    border: 0;
    margin: 0;
    padding: 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .rule h4 {
    margin: 0 0 var(--space-1);
  }

  .rule-fields {
    display: flex;
    flex-flow: row wrap;
    align-items: center;
    gap: var(--space-2) var(--space-5);
  }
</style>
