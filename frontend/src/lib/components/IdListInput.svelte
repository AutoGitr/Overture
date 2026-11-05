<script lang="ts">
  import { parseIds } from "../utils/collectionCriteria";

  /** TMDB IDs or page URLs, separated by commas; what is typed stays until it is valid. */
  let {
    ids,
    label,
    placeholder,
    onchange,
  }: {
    ids: number[];
    /** Names the input for assistive technology. */
    label: string;
    placeholder: string;
    onchange: (ids: number[]) => void;
  } = $props();

  // Starts over only when the IDs change, so an entry being fixed is never dropped.
  let text = $derived(ids.join(", "));
</script>

<input
  required
  aria-label={label}
  {placeholder}
  value={text}
  oninput={(event) => {
    text = event.currentTarget.value;
    event.currentTarget.setCustomValidity("");
  }}
  onchange={(event) => {
    const input = event.currentTarget;
    const { ids: parsed, invalid } = parseIds(input.value);
    if (invalid.length) {
      input.setCustomValidity(`Not a TMDB ID or link: ${invalid.join(", ")}`);
      input.reportValidity();
      return;
    }
    onchange(parsed);
  }}
/>
