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
