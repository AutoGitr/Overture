export type DisplayField = {
  key: string;
  value: string;
};

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function jsonValue(value: unknown): string {
  try {
    const json = JSON.stringify(value);
    return json === undefined ? String(value) : json;
  } catch {
    return "unserializable";
  }
}

function displayValue(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  if (Array.isArray(value)) return value.length === 0 ? "[]" : jsonValue(value);
  return jsonValue(value);
}

/** Every field of *record* in its own order, nested records flattened to dotted keys. */
export function dbRecordFields(record: object | null | undefined, prefix = ""): DisplayField[] {
  if (!record) return [];

  return Object.entries(record).flatMap(([key, value]) => {
    const fieldKey = prefix ? `${prefix}.${key}` : key;
    if (!isPlainRecord(value)) {
      return [{ key: fieldKey, value: displayValue(value) }];
    }

    const fields = dbRecordFields(value, fieldKey);
    return fields.length > 0 ? fields : [{ key: fieldKey, value: "{}" }];
  });
}
