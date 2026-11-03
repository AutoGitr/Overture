<script lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import Music from "@lucide/svelte/icons/music";
  import type { StatusTone } from "../utils/sidebarDomain";
  import StatusTab from "./StatusTab.svelte";
  let {
    mode,
    artStatus,
    themeStatus,
    onart,
    onthemes,
    onclearart = null,
    oncleartheme = null,
    artBusy = false,
    themeBusy = false,
  }: {
    mode: "art" | "themes" | "configure";
    artStatus: StatusTone | null;
    themeStatus: StatusTone | null;
    onart: () => void;
    onthemes: () => void;
    onclearart?: (() => void) | null;
    oncleartheme?: (() => void) | null;
    artBusy?: boolean;
    themeBusy?: boolean;
  } = $props();
</script>

<StatusTab
  icon={Image}
  label="Art"
  active={mode === "art"}
  status={artStatus}
  onselect={onart}
  clearLabel="Clear all art"
  onclear={onclearart}
  clearDisabled={artBusy}
/>
<StatusTab
  icon={Music}
  label="Themes"
  active={mode === "themes"}
  status={themeStatus}
  onselect={onthemes}
  clearLabel="Clear theme"
  onclear={oncleartheme}
  clearDisabled={themeBusy}
/>
