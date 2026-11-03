import { readJson, writeJson } from "./storage";

/** One persisted field: its default and optional value normalisation. */
export interface PersistedField<TValue> {
  default: TValue;
  /** Normalises a stored value before it becomes state (clamping, pruning...). */
  revive?: (value: TValue) => TValue;
}

type FieldSpec<TValue> = TValue | PersistedField<TValue>;

export type PersistedFields<TValues> = {
  [K in keyof TValues]: FieldSpec<TValues[K]>;
};

/** A reactive settings object plus the one call that writes it back. */
export type PersistedState<TValues> = TValues & { save(): void };

function isFieldSpec<TValue>(spec: FieldSpec<TValue>): spec is PersistedField<TValue> {
  return (
    typeof spec === "object" &&
    spec !== null &&
    !Array.isArray(spec) &&
    "default" in (spec as object)
  );
}

function normaliseField<TValue>(spec: FieldSpec<TValue>): PersistedField<TValue> {
  return isFieldSpec(spec) ? spec : { default: spec };
}

/**
 * Declare a group of browser-persisted settings as one reactive object.
 *
 * Persistence is explicit: call `save()` when the values are ready to be
 * written. Callers that load asynchronously can therefore avoid overwriting
 * stored settings with defaults before the real values arrive.
 *
 * The reserved field name `save` cannot be persisted.
 */
export function persistedState<TValues extends Record<string, unknown>>(
  prefix: string,
  fields: PersistedFields<TValues>,
): PersistedState<TValues> {
  const specs = Object.entries(fields).map(([name, spec]) => {
    const field = normaliseField(spec as FieldSpec<unknown>);
    return { name, field, key: `${prefix}_${name}` };
  });

  const initial = {} as Record<string, unknown>;
  for (const { name, field, key } of specs) {
    const stored = readJson(key, field.default);
    initial[name] = field.revive ? field.revive(stored) : stored;
  }

  const values = $state(initial) as PersistedState<TValues>;
  values.save = () => {
    for (const { name, key } of specs) {
      writeJson(key, values[name]);
    }
  };
  return values;
}
