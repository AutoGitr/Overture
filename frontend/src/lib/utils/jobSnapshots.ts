import { createMutation } from "@tanstack/svelte-query";
import { clearJobSnapshot } from "../../generated/rest/sdk.gen";
import type { ClearableJobKind } from "../../generated/ws";
import { JOB_STATES } from "../realtime/jobs";
import { sdkData } from "../rest/sdk";
import type { Notifier } from "../stores/notificationState.svelte";
import { errorMessage } from "./errors";

/**
 * Clear a job's last result here and on the server, unless another run has
 * replaced it since; returns whether it was cleared.
 */
export async function clearJobResult(kind: ClearableJobKind): Promise<boolean> {
  const state = JOB_STATES[kind];
  if (state.finished_at) {
    const response = await sdkData(
      clearJobSnapshot({
        path: { kind },
        query: { finished_at: state.finished_at },
        throwOnError: true,
      }),
    );
    if (response.status === "stale") return false;
  }
  state.reset();
  return true;
}

/**
 * A request that clears the last results of the jobs *kinds* names, telling
 * the user through *feedback* when another run replaced them first.
 */
export function createClearResults(kinds: () => ClearableJobKind[], feedback: Notifier) {
  return createMutation(() => ({
    mutationFn: async () => (await Promise.all(kinds().map(clearJobResult))).every(Boolean),
    onMutate: () => feedback.clear(),
    onSuccess: (cleared: boolean) => {
      if (!cleared) feedback.warning("Results changed; reopen the popup before clearing.");
    },
    onError: (error: unknown) => feedback.error(errorMessage(error, "Failed to clear results")),
  }));
}
