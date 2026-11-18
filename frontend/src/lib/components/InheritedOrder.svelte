<script lang="ts" generics="T extends string">
  import { moveOrderedSource } from "../utils/assetsPopup";
  import { keysOf } from "../utils/records";
  import FieldRow from "./FieldRow.svelte";
  import SourceOrderList from "./SourceOrderList.svelte";

  let {
    label,
    inherits,
    value,
    onchange,
    inherited,
    labels,
    none,
    hint,
  }: {
    label: string;
    /** Offer Default, which follows the order named in it. */
    inherits: boolean;
    /** The ticked entries, first to last; null follows Default. */
    value: readonly T[] | null | undefined;
    onchange: (value: T[] | null) => void;
    inherited?: readonly T[] | null;
    /** Every entry, in the order an unticked one is listed after the ticked. */
    labels: Readonly<Record<T, string>>;
    /** What no ticked entry means, such as Off. */
    none: string;
    hint?: string;
  } = $props();

  const id = $props.id();
  let ticked = $derived<readonly T[]>(value ?? inherited ?? []);
  let order = $derived([...ticked, ...keysOf(labels).filter((entry) => !ticked.includes(entry))]);

  /** The ticked entries as users read them, such as "OvertureDB, then TMDB". */
  function summary(entries: readonly T[] | null | undefined) {
    return entries?.length ? entries.map((entry) => labels[entry]).join(", then ") : none;
  }
</script>

<FieldRow {label} {hint}>
  <div class="order">
    {#if inherits}
      <label class="checkbox-group">
        <input
          type="checkbox"
          checked={value == null}
          onchange={(event) => onchange(event.currentTarget.checked ? null : [...ticked])}
        />
        <span>Default ({summary(inherited)})</span>
      </label>
    {/if}
    {#if !inherits || value != null}
      <SourceOrderList
        sourceOrder={order}
        selectedSources={ticked}
        {labels}
        storageKey={id}
        ontoggle={(entry) =>
          onchange(
            order.filter((other) =>
              other === entry ? !ticked.includes(entry) : ticked.includes(other),
            ),
          )}
        onmove={(entry, target) =>
          onchange(moveOrderedSource(order, entry, target).filter((other) => ticked.includes(other)))}
      />
    {/if}
  </div>
</FieldRow>

<style>
  .order {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: min(100%, 16rem);
  }
</style>
