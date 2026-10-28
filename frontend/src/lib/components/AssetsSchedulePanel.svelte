<script lang="ts">
  import { ART_SOURCE_LABELS, THEME_SOURCE_LABELS } from "../../generated/settings";
  import type {
    BulkAssetsScheduleResponse,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import type { BulkAssetsRequest } from "../utils/assetsPopup";
  import {
    artTypeSummary,
    librarySummary,
    sourceSummary,
    workflowSummary,
  } from "../utils/assetsPopup";
  import type { ScheduleController } from "../utils/schedules.svelte";
  import Schedules from "./Schedules.svelte";

  let {
    canSchedule,
    scheduleCronExpression,
    controller,
    libraries,
    oncronchange,
    onedit,
  }: {
    canSchedule: boolean;
    scheduleCronExpression: string;
    controller: ScheduleController<BulkAssetsRequest, BulkAssetsScheduleResponse>;
    libraries: LibrarySectionRead[];
    /** The cron expression lives in the shared configuration, which the popup owns. */
    oncronchange: (value: string) => void;
    /** Loading a schedule also rewrites the shared configuration, which the popup owns. */
    onedit: (schedule: BulkAssetsScheduleResponse) => void;
  } = $props();
</script>

<Schedules
  {controller}
  emptyMessage="No saved assets schedules."
  {onedit}
  cronExpression={scheduleCronExpression}
  namePlaceholder="Nightly assets"
  {oncronchange}
  unavailable={canSchedule
    ? undefined
    : "Sidebar items can only be run now. Select libraries to save a schedule."}
>
  {#snippet badges(schedule)}
    <span class="badge badge-muted">{workflowSummary(schedule.config)}</span>
  {/snippet}
  {#snippet details(schedule)}
    <div>Libraries: {librarySummary(schedule.config.library_ids ?? [], libraries)}</div>
    <div>Include unmonitored: {schedule.config.include_unmonitored ? "Yes" : "No"}</div>
    <div>Replace existing: {schedule.config.overwrite_existing ? "Yes" : "No"}</div>
    <div>
      Skip checked: {schedule.config.skip_recent_val ?? 0}
      {schedule.config.skip_recent_unit ?? "hours"}
    </div>
    {#if schedule.config.art}
      <div>Art types: {artTypeSummary(schedule.config.art.art_types ?? [])}</div>
      <div>
        Art sources:
        {sourceSummary(schedule.config.art.source_order ?? [], ART_SOURCE_LABELS)}
      </div>
      <div>
        Threshold: {schedule.config.art.threshold === -1
          ? "Perfect match"
          : schedule.config.art.threshold}
      </div>
    {/if}
    {#if schedule.config.themes}
      <div>
        Theme sources:
        {sourceSummary(schedule.config.themes.source_order ?? [], THEME_SOURCE_LABELS)}
      </div>
    {/if}
  {/snippet}
</Schedules>
