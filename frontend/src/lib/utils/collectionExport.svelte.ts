import { createMutation } from "@tanstack/svelte-query";
import { exportCollectionPresetMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
import type { PresetExportRequest } from "../../generated/rest/types.gen";
import { createNotifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";
import { countOf } from "./plural";

/** A file name from *title*, kept to letters, digits and dashes. */
function fileName(title: string) {
  const slug = title
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `overture-${slug || "collections"}.json`;
}

/**
 * Export groups, with their sets, and collections as a portable file, which
 * another install loads beside Presets and OvertureDB takes as a preset.
 */
export class CollectionExport {
  private readonly request = createMutation(() => exportCollectionPresetMutation());
  private readonly feedback = createNotifier();

  get busy() {
    return this.request.isPending;
  }

  /** Download what *body* chooses, named after *title*; say what was left out and why. */
  async run(body: PresetExportRequest, title: string) {
    this.feedback.clear();
    let exported;
    try {
      exported = await this.request.mutateAsync({ body });
    } catch (error) {
      this.feedback.error(errorMessage(error, "Could not export the collections"));
      return;
    }
    const notes = [
      ...(exported.refused ?? []).map((refusal) => `Left out ${refusal.title}: ${refusal.reason}`),
      ...(exported.warnings ?? []),
    ].join("\n");
    const file = exported.file;
    if (!file) {
      this.feedback.error(notes || "Nothing chosen can be exported", {
        title: "Nothing to export",
      });
      return;
    }
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(file, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName(title);
    link.click();
    // Following the link resolves the blob URL at once, so the download keeps
    // the file after the URL is revoked.
    URL.revokeObjectURL(url);
    const issue = exported.issue?.url;
    const count = file.groups.length + file.collections.length;
    (notes ? this.feedback.warning : this.feedback.success)(
      notes || "Load it beside Presets on another install, or contribute it to OvertureDB.",
      {
        title: `Exported ${countOf(count, "group or collection", "groups and collections")}`,
        action: issue
          ? {
              label: "Contribute to OvertureDB",
              run: () => window.open(issue, "_blank", "noopener"),
            }
          : undefined,
      },
    );
  }
}
