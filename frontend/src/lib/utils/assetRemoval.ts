import { getRemovalOptions } from "../../generated/rest/sdk.gen";
import type { AssetRemoval, RemovalOption, RemovalTarget } from "../../generated/rest/types.gen";
import { sdkData } from "../rest/sdk";
import { selectActions, type ConfirmChoice } from "../stores/notificationState.svelte";

type RemovalChoice = keyof AssetRemoval;

const CHOICES: readonly { value: RemovalChoice; label: string; description: string }[] = [
  {
    value: "forget",
    label: "Forget the selection",
    description: "Overture stops choosing it; files stay.",
  },
  {
    value: "delete_file",
    label: "Delete the local file",
    description: "The image or MP3 theme in the media folder.",
  },
  {
    value: "delete_from_server",
    label: "Delete from the media server",
    description: "The copy the media server shows.",
  },
];

/** What a choice would change: how many of several targets, or nothing said for one. */
function detail(option: RemovalOption, description: string, several: boolean): string {
  return several ? `${description} Applies to ${option.count}.` : description;
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
  const several = (target.item_ids?.length ?? 0) + (target.collection_ids?.length ?? 0) > 1;
  const choices: ConfirmChoice<RemovalChoice>[] = CHOICES.map((choice) => ({
    value: choice.value,
    label: choice.label,
    description: detail(options[choice.value], choice.description, several),
    unavailable: options[choice.value].unavailable ?? undefined,
  }));
  const chosen = await selectActions({
    title: `Remove ${what}?`,
    message:
      "Choose what to remove, in any combination. Overture only deletes images and MP3 themes.",
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
