import FolderPen from "@lucide/svelte/icons/folder-pen";
import Image from "@lucide/svelte/icons/image";
import RefreshCw from "@lucide/svelte/icons/refresh-cw";
import ShieldCheck from "@lucide/svelte/icons/shield-check";
import { assetManagerState } from "./assetManagerState.svelte";
import { themeJobState } from "./bulkJobState.svelte";
import { syncState } from "./jobStates.svelte";
import { matchState } from "./matchState.svelte";
import { serverAuditFixState } from "./serverAuditFixState.svelte";
import { serverAuditState } from "./serverAuditState.svelte";
import type { OperationsTab } from "./uiState.svelte";

/** One of the operations the Operations window runs, with the jobs behind it. */
export interface Operation {
  readonly label: string;
  readonly icon: typeof Image;
  /** What the operation does, for its tab's description. */
  readonly about: string;
  /** Whether one of its jobs runs now. */
  readonly running: boolean;
  /** Whether its tab holds a run's results. */
  readonly hasRun: boolean;
}

/** Each operation, in the order its tab and button are shown. */
export const OPERATIONS: Readonly<Record<OperationsTab, Operation>> = {
  assets: {
    label: "Assets",
    icon: Image,
    about:
      "Finds and downloads art and theme music for the chosen libraries or sidebar items. " +
      "Sources are tried top to bottom and the first match wins. Files you already have are " +
      "kept unless you choose otherwise.",
    get running() {
      return matchState.running || themeJobState.running;
    },
    get hasRun() {
      return matchState.hasRun || themeJobState.hasRun;
    },
  },
  sync: {
    label: "Sync",
    icon: RefreshCw,
    about:
      "Imports your media server's libraries into Overture: new items, metadata, paths and " +
      "local files. Items the server no longer lists are hidden, never deleted from disk. " +
      "Also checks TMDB for new seasons of saved shows.",
    get running() {
      return syncState.running;
    },
    get hasRun() {
      return syncState.hasRun;
    },
  },
  renamer: {
    label: "Renamer",
    icon: FolderPen,
    about:
      "Finds misnamed art and theme files in your media folders, then renames the ones you " +
      "select. Art types are guessed from image size, so check each suggestion first. " +
      "Nothing is downloaded or converted.",
    get running() {
      return assetManagerState.running;
    },
    get hasRun() {
      return assetManagerState.hasRun;
    },
  },
  audit: {
    label: "Server Audit",
    icon: ShieldCheck,
    about:
      "Checks that your media server shows the same art and themes as your local files, " +
      "then lets you refresh the ones that differ. Only monitored items with local files " +
      "are checked.",
    get running() {
      return serverAuditState.running || serverAuditFixState.running;
    },
    get hasRun() {
      return serverAuditState.hasRun;
    },
  },
};

export const OPERATION_TABS = Object.keys(OPERATIONS) as OperationsTab[];
