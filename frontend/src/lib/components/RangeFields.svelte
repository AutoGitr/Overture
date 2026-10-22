<script lang="ts">
  let {
    minLabel,
    maxLabel,
    min = $bindable(),
    max = $bindable(),
  }: {
    minLabel: string;
    maxLabel: string;
    min: number | null;
    max: number | null;
  } = $props();

  const id = $props.id();
</script>

<div class="range">
  <div class="field">
    <label class="form-label" for="{id}-min">{minLabel}</label>
    <input
      id="{id}-min"
      type="number"
      class="number-input"
      min="1"
      placeholder="No limit"
      bind:value={min}
    />
  </div>
  <div class="field">
    <label class="form-label" for="{id}-max">{maxLabel}</label>
    <input
      id="{id}-max"
      type="number"
      class="number-input"
      min="1"
      placeholder="No limit"
      bind:value={max}
    />
  </div>
</div>

<style>
  .range {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-4);
  }

  .field {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-1) var(--space-2);
  }

  .number-input {
    flex: 1;
    min-width: 0;
    width: 80px;
    padding: var(--space-1) var(--space-2);
  }

  @media (max-width: 480px) {
    .field {
      flex-direction: column;
      align-items: stretch;
    }

    .number-input {
      width: 100%;
    }
  }
</style>
