/** A form draft; assigning `current` replaces it with a copy of what is assigned. */
interface Draft<T> {
  current: T;
}

/**
 * An editable, deeply reactive copy of saved data, taken the first time
 * *saved* returns some, and until then *initial*, or null without one.
 *
 * Once taken it no longer reads *saved*, so a refetch, such as one a sync's
 * broadcasts start, never undoes an edit, even when the data it brings differs.
 */
export function draftOf<T>(saved: () => T | null | undefined): Draft<T | null>;
export function draftOf<T>(saved: () => T | null | undefined, initial: T): Draft<T>;
export function draftOf<T>(saved: () => T | null | undefined, initial: T | null = null) {
  // Not state: holding the copy taken keeps the draft from reading *saved* again.
  let taken: { copy: T | null } | null = null;
  const editable = (value: T | null) => {
    const copy = $state($state.snapshot(value) as T | null);
    return copy;
  };
  let draft = $derived.by(() => {
    if (taken) return taken.copy;
    const value = saved();
    const copy = editable(value ?? initial);
    if (value != null) taken = { copy };
    return copy;
  });
  return {
    get current() {
      return draft;
    },
    set current(value) {
      const copy = editable(value);
      taken = { copy };
      draft = copy;
    },
  };
}
