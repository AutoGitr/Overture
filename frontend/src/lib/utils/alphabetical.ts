/** *items* in alphabetical order of their labels, for lists with no order of their own. */
export function alphabetical<T>(items: readonly T[], label: (item: T) => string): T[] {
  return [...items].sort((a, b) => label(a).localeCompare(label(b)));
}
