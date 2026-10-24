import type { Component } from "svelte";
import type { PopupType } from "../stores/uiState.svelte";
import BackupPopup from "./BackupPopup.svelte";
import DbRecordPopup from "./DbRecordPopup.svelte";
import FiltersPopup from "./FiltersPopup.svelte";
import OperationsPopup from "./OperationsPopup.svelte";
import OvertureDbPopup from "./OvertureDbPopup.svelte";
import SettingsPopup from "./SettingsPopup.svelte";
import StatsPopup from "./StatsPopup.svelte";
import NewCollectionModal from "../components/NewCollectionModal.svelte";
import CollectionGeneratorModal from "../components/CollectionGeneratorModal.svelte";

type ActivePopupType = Exclude<PopupType, null>;

export const POPUP_COMPONENTS = {
  filters: FiltersPopup,
  operations: OperationsPopup,
  settings: SettingsPopup,
  overturedb: OvertureDbPopup,
  database: DbRecordPopup,
  backup: BackupPopup,
  stats: StatsPopup,
  newCollection: NewCollectionModal,
  collectionGenerator: CollectionGeneratorModal,
} satisfies Record<ActivePopupType, Component>;
