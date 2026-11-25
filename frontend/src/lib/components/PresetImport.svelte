<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import {
    importCollectionPresetMutation,
    planCollectionPresetMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionPresetFileInput,
    LibrarySectionRead,
    MediaType,
    PresetPlanItem,
  } from "../../generated/rest/types.gen";
  import { invalidateTags } from "../rest/cache";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { errorMessage } from "../utils/errors";
  import CheckboxList from "./CheckboxList.svelte";
  import Select from "./Select.svelte";

  let {
    file,
    libraries,
  }: {
    /** The file to add, as a preset or an export holds it. */
    file: CollectionPresetFileInput;
    libraries: readonly LibrarySectionRead[];
  } = $props();

  /** The media types the file's collections and sets hold. */
  let mediaTypes = $derived(
    (["movie", "show"] as const).filter(
      (mediaType) =>
        (file.collections ?? []).some((collection) => mediaType in collection.criteria) ||
        (file.groups ?? []).some((group) => group.generator?.media_types.includes(mediaType)),
    ),
  );
  /** The library chosen for each media type, the first of its kind until one is picked. */
  let chosen = $derived<Partial<Record<MediaType, string>>>(
    Object.fromEntries(
      mediaTypes.map((mediaType) => [
        mediaType,
        libraries.find((library) => library.media_type === mediaType)?.id,
      ]),
    ),
  );
  /** What the file would add, from the last preview; a new file starts unchecked. */
  let planned = $derived.by<PresetPlanItem[] | null>(() => {
    void file;
    return null;
  });
  let warnings = $derived.by<string[]>(() => {
    void file;
    return [];
  });
  /** The items of the preview someone unticked, by name. */
  let skipped = $derived.by<string[]>(() => {
    void file;
    return [];
  });
  /** What adding the file did. */
  let added = $derived.by<PresetPlanItem[] | null>(() => {
    void file;
    return null;
  });

  const feedback = createNotifier();
  const planRequest = createMutation(() => planCollectionPresetMutation());
  const importRequest = createMutation(() => importCollectionPresetMutation());

  function body() {
    return {
      file,
      libraries: Object.fromEntries(
        Object.entries(chosen)
          .filter(([, library]) => library)
          .map(([mediaType, library]) => [mediaType, [library as string]]),
      ),
    };
  }

  async function preview() {
    feedback.clear();
    added = null;
    try {
      const plan = await planRequest.mutateAsync({ body: body() });
      planned = plan.items ?? [];
      skipped = planned.filter((item) => !item.chosen).map((item) => item.name);
      warnings = plan.warnings ?? [];
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to check the collections"));
    }
  }

  async function add() {
    feedback.clear();
    try {
      const result = await importRequest.mutateAsync({ body: { ...body(), skip: skipped } });
      added = result.items ?? [];
      planned = null;
      // The gallery says which presets are added, and in which version.
      void invalidateTags(["collections"]);
      const count = result.collection_ids?.length ?? 0;
      feedback.success(`Added ${count} collection${count === 1 ? "" : "s"}`);
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to add the collections"));
    }
  }

  /** How each status reads before and after adding. */
  const STATUS_LABELS: Record<PresetPlanItem["status"], [string, string]> = {
    add: ["Adds", "Added"],
    update: ["Updates", "Updated"],
    skip: ["Skips", "Skipped"],
    refused: ["Cannot add", "Not added"],
  };
  const STATUS_TONES: Record<PresetPlanItem["status"], string> = {
    add: "badge-success",
    update: "badge-warning",
    skip: "badge-muted",
    refused: "badge-danger",
  };
  const choosable = (item: PresetPlanItem) => item.status === "add" || item.status === "update";
  const label = (item: PresetPlanItem) =>
    `${item.kind === "group" ? "Group" : "Collection"} ${item.name}`;
</script>

<div class="preset-import">
  {#each mediaTypes as mediaType (mediaType)}
    {@const options = libraries
      .filter((library) => library.media_type === mediaType)
      .map((library) => ({ value: library.id, label: library.title }))}
    <div class="form-label">
      <span>Library for {mediaType}s</span>
      <Select
        label="Library for {mediaType}s"
        {options}
        placeholder="No {mediaType} library"
        bind:value={
          () => chosen[mediaType] ?? null,
          (library) => (chosen = { ...chosen, [mediaType]: library ?? undefined })
        }
      />
    </div>
  {/each}

  <button
    type="button"
    class="btn btn-secondary"
    disabled={planRequest.isPending}
    onclick={preview}>Preview</button
  >

  {#each warnings as warning (warning)}
    <p class="hint">{warning}</p>
  {/each}

  {#if planned ?? added}
    {@const items = (planned ?? added)!}
    <ul class="plan" aria-label={planned ? "What adding does" : "What was added"}>
      {#each items as item (`${item.kind}:${item.name}`)}
        <li>
          <span class={["badge", STATUS_TONES[item.status]]}
            >{STATUS_LABELS[item.status][added ? 1 : 0]}</span
          >
          <span>{label(item)}</span>
          {#if item.reason}<span class="hint">{item.reason}</span>{/if}
        </li>
      {/each}
    </ul>
    {#if planned?.some(choosable)}
      <fieldset class="include">
        <legend>Include</legend>
        <CheckboxList
          options={planned.filter(choosable).map((item) => ({ value: item.name, label: label(item) }))}
          selected={planned
            .filter((item) => choosable(item) && !skipped.includes(item.name))
            .map((item) => item.name)}
          ontoggle={(name) =>
            (skipped = skipped.includes(name)
              ? skipped.filter((other) => other !== name)
              : [...skipped, name])}
        />
      </fieldset>
      <button
        type="button"
        class="btn btn-primary"
        disabled={importRequest.isPending ||
          planned.every((item) => !choosable(item) || skipped.includes(item.name))}
        onclick={add}>Add</button
      >
    {/if}
  {/if}
</div>

<style>
  .preset-import {
    display: grid;
    gap: var(--space-3);
  }

  .form-label {
    display: grid;
    gap: var(--space-2);
  }

  .plan {
    display: grid;
    gap: var(--space-2);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .include {
    margin: 0;
    padding: 0;
    border: 0;
  }

  .plan li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-2);
  }
</style>
