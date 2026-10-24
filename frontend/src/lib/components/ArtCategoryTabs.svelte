<script module lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import MountainSnow from "@lucide/svelte/icons/mountain-snow";
  import type { ArtType } from "../../generated/rest/types.gen";
  import type { ArtSubTab } from "../router/routes";

  export const ART_TABS: readonly {
    key: ArtSubTab;
    label: string;
    icon: typeof Image;
    artType: ArtType;
    statusField: "poster_status" | "background_status" | "season_posters_status";
  }[] = [
    {
      key: "poster",
      label: "Poster",
      icon: Image,
      artType: "poster",
      statusField: "poster_status",
    },
    {
      key: "background",
      label: "Background",
      icon: MountainSnow,
      artType: "background",
      statusField: "background_status",
    },
    {
      key: "seasons",
      label: "Seasons",
      icon: Layers,
      artType: "season_poster",
      statusField: "season_posters_status",
    },
  ];
</script>

<script lang="ts">
  import type { StatusTone } from "../utils/sidebarDomain";
  import StatusTab from "./StatusTab.svelte";

  let {
    active,
    seasons = false,
    statuses = {},
    clearable = {},
    clearDisabled = false,
    clearSeason = false,
    onselect,
    onclear,
  }: {
    active: ArtSubTab;
    seasons?: boolean;
    statuses?: Partial<Record<ArtSubTab, StatusTone | null>>;
    clearable?: Partial<Record<ArtSubTab, boolean>>;
    clearDisabled?: boolean;
    clearSeason?: boolean;
    onselect: (tab: ArtSubTab) => void;
    onclear?: (tab: ArtSubTab) => void;
  } = $props();
</script>

{#each ART_TABS.filter((tab) => tab.key !== "seasons" || seasons) as tab (tab.key)}
  <StatusTab
    icon={tab.icon}
    label={tab.label}
    active={active === tab.key}
    status={statuses[tab.key]}
    onselect={() => onselect(tab.key)}
    clearLabel={tab.key === "seasons" && clearSeason
      ? "Clear season poster"
      : `Clear ${tab.label.toLowerCase()}`}
    onclear={clearable[tab.key] && onclear ? () => onclear?.(tab.key) : null}
    {clearDisabled}
  />
{/each}
