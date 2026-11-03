/** Return the keys of *record*, typed as the record's keys. */
export function keysOf<K extends string>(record: Record<K, unknown>): K[] {
  // Object.keys widens to string[]; a Record's own keys are exactly K.
  return Object.keys(record) as K[];
}
