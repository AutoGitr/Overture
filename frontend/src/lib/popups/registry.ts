import type { Component } from "svelte";
import type { PopupType } from "../stores/uiState.svelte";
import CollectionGroupsPopup from "./CollectionGroupsPopup.svelte";
import BackupPopup from "./BackupPopup.svelte";
import DbRecordPopup from "./DbRecordPopup.svelte";
import FiltersPopup from "./FiltersPopup.svelte";
import OperationsPopup from "./OperationsPopup.svelte";
import OvertureDbPopup from "./OvertureDbPopup.svelte";
import SettingsPopup from "./SettingsPopup.svelte";
import StatsPopup from "./StatsPopup.svelte";

type ActivePopupType = Exclude<PopupType, null>;

export const POPUP_COMPONENTS = {
  "collection-groups": CollectionGroupsPopup,
  filters: FiltersPopup,
  operations: OperationsPopup,
  settings: SettingsPopup,
  overturedb: OvertureDbPopup,
  database: DbRecordPopup,
  backup: BackupPopup,
  stats: StatsPopup,
} satisfies Record<ActivePopupType, Component>;
