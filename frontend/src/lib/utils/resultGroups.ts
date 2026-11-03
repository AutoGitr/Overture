import type { LogTone } from "./jobLog";

/** Results of one kind, which a results view shows or hides together. */
export interface ResultGroup<K extends string = string> {
  key: K;
  label: string;
  count: number;
  shown: boolean;
  tone?: LogTone;
}

/** Sort *groups* in the order *order* lists their keys; unlisted ones follow by label. */
export function orderGroups<G extends ResultGroup>(
  groups: Iterable<G>,
  order: readonly string[],
): G[] {
  const rank = (group: G) => {
    const index = order.indexOf(group.key);
    return index === -1 ? order.length : index;
  };
  return [...groups].sort(
    (left, right) => rank(left) - rank(right) || left.label.localeCompare(right.label),
  );
}
