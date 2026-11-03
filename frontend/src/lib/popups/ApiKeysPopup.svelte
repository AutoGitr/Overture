<script lang="ts">
  import Copy from "@lucide/svelte/icons/copy";
  import KeyRound from "@lucide/svelte/icons/key-round";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import {
    createApiKeyMutation,
    deleteApiKeyMutation,
    listApiKeysOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { ApiKeyCreated, ApiKeyRead } from "../../generated/rest/types.gen";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { formatDateInTimezone } from "../utils/popupFormat";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";

  const queryClient = useQueryClient();
  const keysQuery = createQuery(() => listApiKeysOptions());
  const createRequest = createMutation(() => createApiKeyMutation());
  const deleteRequest = createMutation(() => deleteApiKeyMutation());
  const feedback = createNotifier();
  // The clipboard API exists only in secure contexts; elsewhere the key is selected to copy.
  const canCopy = typeof navigator !== "undefined" && navigator.clipboard !== undefined;

  let name = $state("");
  /** The key just created: the server never returns it again. */
  let created = $state<ApiKeyCreated | null>(null);
  let keys = $derived(keysQuery.data ?? []);

  function setKeys(update: (current: ApiKeyRead[]) => ApiKeyRead[]) {
    queryClient.setQueryData(listApiKeysOptions().queryKey, (current) => update(current ?? []));
  }

  async function create(event: SubmitEvent) {
    event.preventDefault();
    feedback.clear();
    try {
      const key = await createRequest.mutateAsync({ body: { name } });
      setKeys((current) => [...current, { id: key.id, name: key.name, created_at: key.created_at }]);
      created = key;
      name = "";
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to create the API key"));
    }
  }

  async function revoke(key: ApiKeyRead) {
    const confirmed = await confirmAction({
      title: "Revoke API key",
      message: `Anything using "${key.name}" stops working at once.`,
      confirmLabel: "Revoke",
      destructive: true,
    });
    if (!confirmed) return;
    feedback.clear();
    try {
      await deleteRequest.mutateAsync({ path: { key_id: key.id } });
      setKeys((current) => current.filter((entry) => entry.id !== key.id));
      if (created?.id === key.id) created = null;
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to revoke the API key"));
    }
  }

  async function copy(key: string) {
    try {
      await navigator.clipboard.writeText(key);
      feedback.success("API key copied.");
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to copy the API key"));
    }
  }
</script>

<PopupShell title="API keys" size="form" onclose={() => uiState.closePopup()}>
  {#snippet icon()}
    <KeyRound size={18} />
  {/snippet}
  <div class="keys">
    <span class="hint">
      Read-only keys for dashboards and scripts. Send one as the <code>X-Api-Key</code> header.
    </span>
    <DataStatus
      label="API keys"
      error={keysQuery.error}
      loading={keysQuery.isFetching}
      hasData={keysQuery.data !== undefined}
      onretry={() => keysQuery.refetch()}
    />
    {#if keys.length > 0}
      <ul class="key-list" aria-label="API keys">
        {#each keys as key (key.id)}
          <li class="key-item">
            <span class="key-name">{key.name}</span>
            <span class="text-tertiary">{formatDateInTimezone(key.created_at)}</span>
            <button
              type="button"
              class="btn btn-ghost btn-icon btn-sm"
              aria-label={`Revoke ${key.name}`}
              disabled={deleteRequest.isPending}
              onclick={() => revoke(key)}
            >
              <Trash2 size={14} />
            </button>
          </li>
        {/each}
      </ul>
    {/if}
    {#if created}
      <div class="created" role="status">
        <label for="created-api-key">Copy the key for {created.name} now; it is not shown again.</label>
        <div class="form-row">
          <input
            id="created-api-key"
            class="text-input text-input-mono flex-1"
            readonly
            value={created.key}
            onfocus={(event) => event.currentTarget.select()}
          />
          {#if canCopy}
            <button type="button" class="btn btn-secondary btn-sm" onclick={() => copy(created!.key)}>
              <Copy size={14} /> Copy
            </button>
          {/if}
        </div>
      </div>
    {/if}
    <form class="form-row" onsubmit={create}>
      <label for="new-api-key-name" class="sr-only">New API key name</label>
      <input
        id="new-api-key-name"
        class="text-input flex-1"
        placeholder="Name, such as Homepage"
        maxlength="100"
        required
        bind:value={name}
      />
      <button
        type="submit"
        class="btn btn-secondary btn-sm"
        disabled={createRequest.isPending || !name.trim()}
      >
        Create
      </button>
    </form>
  </div>
  {#snippet footer()}
    <button type="button" class="btn btn-secondary" onclick={() => uiState.closePopup()}>Close</button>
  {/snippet}
</PopupShell>

<style>
  .keys {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .key-list {
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .key-item {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
    background: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    font-size: var(--text-xs);
  }

  .key-name {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--text-primary);
  }

  .created {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    font-size: var(--text-xs);
  }
</style>
