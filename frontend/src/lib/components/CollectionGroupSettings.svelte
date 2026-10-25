<script lang="ts">
  import { createQuery, createMutation, useQueryClient } from "@tanstack/svelte-query";
  import {
    getCollectionGroupPolicyOptions,
    saveCollectionGroupPolicyMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionGroupPolicyOutput,
    MediaType,
    ServerType,
  } from "../../generated/rest/types.gen";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DataStatus from "./DataStatus.svelte";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { errorMessage } from "../utils/errors";

  let {
    group,
    mediaType,
    serverType,
  }: { group: string; mediaType: MediaType; serverType: ServerType | null } = $props();
  const client = useQueryClient();
  let open = $state(false);
  const query = createQuery(() => ({
    ...getCollectionGroupPolicyOptions({ query: { name: group, media_type: mediaType } }),
    enabled: open,
  }));
  const request = createMutation(() => saveCollectionGroupPolicyMutation());
  const feedback = createNotifier();
  let draft = $derived.by(() => {
    if (!query.data) return null;
    const value = $state<CollectionGroupPolicyOutput>({ ...query.data });
    return value;
  });
  async function save() {
    if (!draft || request.isPending) return;
    const variables = {
      query: { name: group, media_type: mediaType },
      body: $state.snapshot(draft),
    };
    try {
      const saved = await request.mutateAsync(variables);
      client.setQueryData(
        getCollectionGroupPolicyOptions({ query: variables.query }).queryKey,
        saved,
      );
      feedback.success("Group defaults saved. Collections use them on their next save or sync.");
    } catch (error) {
      feedback.error(errorMessage(error, "Could not save group defaults"));
    }
  }
</script>

<details class="form-wide" ontoggle={(event) => (open = event.currentTarget.open)}>
  <summary>Defaults for group: {group}</summary>
  <p class="hint">
    Blank values inherit global defaults. Collection overrides take precedence. Changes apply on the
    next save or sync.
  </p>
  <DataStatus
    label="group defaults"
    error={query.error}
    loading={query.isFetching}
    hasData={query.data !== undefined}
    onretry={() => query.refetch()}
  />
  {#if draft}
    <fieldset class="options-col" disabled={request.isPending}>
      <legend>Group defaults</legend>
      <CollectionPolicyFields policy={draft} prefix="Group " plex={serverType === "plex"} />
      <label class="form-row"
        ><input
          type="checkbox"
          checked={draft.sort_title_format === null}
          onchange={(event) => {
            if (draft) draft.sort_title_format = event.currentTarget.checked ? null : "";
          }}
        />Inherit global sort title template</label
      >
      {#if draft.sort_title_format !== null}<label class="form-label"
          >Group sort title template
          <input maxlength="200" bind:value={draft.sort_title_format} />
          <span class="hint"
            >Use &#123;title&#125; and &#123;group&#125;. Empty disables formatting for this group.</span
          >
        </label>{/if}
      <button type="button" class="btn btn-secondary" onclick={() => void save()}
        >Save group defaults</button
      >
    </fieldset>
  {/if}
</details>
