import { getRemovalOptions } from "../../generated/rest/sdk.gen";
import type {
  AssetRemoval,
  RemovableAsset,
  RemovalOption,
  RemovalTarget,
} from "../../generated/rest/types.gen";
import { sdkData } from "../rest/sdk";
import { selectActions, type ConfirmChoice } from "../stores/notificationState.svelte";

type RemovalChoice = keyof AssetRemoval;

/** What one removed asset is called: the file type and the plural it takes. */
function files(asset: RemovableAsset, several: boolean): string {
  const noun = asset === "theme" ? "MP3 file" : "image file";
  return several ? `${noun}s` : noun;
}

/** Each choice, worded for what is being removed. */
function describe(choice: RemovalChoice, what: string, asset: RemovableAsset, several: boolean) {
  const kept = asset === "theme" ? "the MP3" : "the image";
  switch (choice) {
    case "forget":
      return {
        label: "Forget the selection",
        description: `Overture no longer chooses ${what}; ${kept} stays in the media folder and on the server.`,
      };
    case "delete_file":
      return {
        label: `Delete the local ${files(asset, several)}`,
        description: `Deletes ${what} from the media folder.`,
      };
    case "delete_from_server":
      return {
        label: "Delete from the media server",
        description: `Deletes the copy of ${what} the media server shows.`,
      };
  }
}

const CHOICES: readonly RemovalChoice[] = ["forget", "delete_file", "delete_from_server"];

/** What a choice would change: how many of several targets, or nothing said for one. */
function detail(option: RemovalOption, description: string, several: boolean): string {
  return several ? `${description} Applies to ${option.count}.` : description;
}

function several(target: RemovalTarget): boolean {
  return (target.item_ids?.length ?? 0) + (target.collection_ids?.length ?? 0) > 1;
}

/**
 * Ask what removing *target*'s asset should remove, offering only what applies
 * to it as things stand; resolves the removal, or `null` when cancelled.
 *
 * @param what Names the asset in the dialog, such as "the poster".
 */
export async function askRemoval(
  target: RemovalTarget,
  what: string,
): Promise<AssetRemoval | null> {
  const options = await sdkData(getRemovalOptions({ body: target, throwOnError: true }));
  const many = several(target);
  const choices: ConfirmChoice<RemovalChoice>[] = CHOICES.map((value) => {
    const { label, description } = describe(value, what, target.asset, many);
    return {
      value,
      label,
      description: detail(options[value], description, many),
      unavailable: options[value].unavailable ?? undefined,
    };
  });
  const chosen = await selectActions({
    title: `Remove ${what}?`,
    message: `Choose what to remove, in any combination. Only ${files(target.asset, true)} are deleted.`,
    confirmLabel: "Remove",
    destructive: true,
    choices,
    initial: options.forget.unavailable ? [] : ["forget"],
  });
  if (!chosen) return null;
  return {
    forget: chosen.includes("forget"),
    delete_file: chosen.includes("delete_file"),
    delete_from_server: chosen.includes("delete_from_server"),
  };
}

const list = new Intl.ListFormat("en", { type: "conjunction" });

/**
 * The notice for a removal that succeeded, naming each part it carried out.
 *
 * @param what Names what was removed, as `askRemoval` was told.
 */
export function removedMessage(what: string, removal: AssetRemoval, many = false): string {
  const done = [
    removal.forget && "forgot the selection",
    removal.delete_file && `deleted the local ${many ? "files" : "file"}`,
    removal.delete_from_server && `deleted the media server's ${many ? "copies" : "copy"}`,
  ].filter((part): part is string => typeof part === "string");
  return `Removed ${what}: ${list.format(done)}.`;
}
