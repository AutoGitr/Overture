<script module lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import MountainSnow from "@lucide/svelte/icons/mountain-snow";
  import type { ArtType, AssetStatus, MediaItemRead } from "../../generated/rest/types.gen";
  import type { ArtSubTab } from "../router/routes";
  import { MEDIA_ICONS } from "../utils/mediaIcons";

  export const ART_TABS: readonly {
    key: ArtSubTab;
    label: string;
    icon: typeof Image;
    artType: ArtType;
    status: (item: MediaItemRead) => AssetStatus;
  }[] = [
    {
      key: "poster",
      label: "Poster",
      icon: Image,
      artType: "poster",
      status: (item) => item.assets.poster.status,
    },
    {
      key: "background",
      label: "Background",
      icon: MountainSnow,
      artType: "background",
      status: (item) => item.assets.background.status,
    },
    {
      key: "seasons",
      label: "Seasons",
      icon: MEDIA_ICONS.season,
      artType: "season_poster",
      status: (item) => item.season_posters_status,
    },
  ];
</script>

<script lang="ts">
  import type { StatusTone } from "../utils/sidebarShared";
  import StatusTab from "./StatusTab.svelte";

  let {
    active,
    seasons = false,
    statuses = {},
    notes = {},
    clearable = {},
    clearDisabled = false,
    clearSeason = false,
    onselect,
    onclear,
  }: {
    /** Null outside the art mode, where the tabs only open it. */
    active: ArtSubTab | null;
    seasons?: boolean;
    statuses?: Partial<Record<ArtSubTab, StatusTone | null>>;
    /** Why a tab's status is what it is, shown on hover. */
    notes?: Partial<Record<ArtSubTab, string | null>>;
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
    note={notes[tab.key]}
    onselect={() => onselect(tab.key)}
    clearLabel={tab.key === "seasons" && clearSeason
      ? "Clear season poster"
      : `Clear ${tab.label.toLowerCase()}`}
    onclear={clearable[tab.key] && onclear ? () => onclear?.(tab.key) : null}
    {clearDisabled}
  />
{/each}
