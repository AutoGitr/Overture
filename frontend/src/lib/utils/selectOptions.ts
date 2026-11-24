import { keysOf } from "./records";

/** One choice a `Select` offers. */
export interface SelectOption<V = string> {
  value: V;
  label: string;
  /** A note beside the label, such as how many titles hold it. */
  detail?: string;
  disabled?: boolean;
  /** The heading it is listed under; options sharing one sit together. */
  group?: string;
}

/** Options for values that are their own labels. */
export function toOptions<V extends string>(values: readonly V[]): SelectOption<V>[] {
  return values.map((value) => ({ value, label: value }));
}

/** Options for every value a label map names, in its order. */
export function fromLabels<V extends string>(labels: Record<V, string>): SelectOption<V>[] {
  return keysOf(labels).map((value) => ({ value, label: labels[value] }));
}
