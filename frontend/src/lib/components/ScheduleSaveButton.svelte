<script lang="ts" generics="TConfig, TSchedule extends SavedSchedule<TConfig>">
  import type { SavedSchedule, ScheduleController } from "../utils/schedules.svelte";

  let {
    controller,
    blocker,
    onsave,
  }: {
    controller: ScheduleController<TConfig, TSchedule>;
    /** Why the schedule cannot be saved yet; ``null`` when it can. */
    blocker: string | null;
    onsave: () => void;
  } = $props();
</script>

<button
  class="btn btn-secondary"
  onclick={onsave}
  title={blocker ?? undefined}
  disabled={blocker !== null || controller.saving}
>
  {controller.isEditing ? "Update schedule" : "Save schedule"}
</button>
