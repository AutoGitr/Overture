/** "1 collection", "2 collections": a count with its noun in the right number. */
export function countOf(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`;
}
