export function toggleSelectedValue<T extends string>(values: T[], value: T): T[] {
  return values.includes(value)
    ? values.filter((current) => current !== value)
    : [...values, value];
}

export function filterAvailableValues(
  selectedValues: string[],
  availableValues: string[],
): string[] {
  const available = new Set(availableValues);
  return selectedValues.filter((value) => available.has(value));
}

export function selectedValuesForAll(checked: boolean, availableValues: string[]): string[] {
  return checked ? [...availableValues] : [];
}

export function allValuesSelected(selectedValues: string[], availableValues: string[]): boolean {
  return selectedValues.length === availableValues.length && availableValues.length > 0;
}

/** The collections a run covers: every one, or only the chosen groups. */
export interface CollectionChoice {
  all: boolean;
  groups: string[];
}

/** Toggle every collection (`null`) or one group; choosing one clears the other. */
export function toggleCollectionChoice(
  choice: CollectionChoice,
  group: string | null,
): CollectionChoice {
  return group === null
    ? { all: !choice.all, groups: [] }
    : { all: false, groups: toggleSelectedValue(choice.groups, group) };
}
