type StorageKind = "local" | "session";

function getStorage(kind: StorageKind): Storage {
  return kind === "local" ? localStorage : sessionStorage;
}

/** Decode JSON; callers validate object fields and domain-specific values. */
export function readJson<T>(key: string, fallback: T, kind: StorageKind = "local"): T {
  try {
    const raw = getStorage(kind).getItem(key);
    if (raw === null) return fallback;
    const value: unknown = JSON.parse(raw);
    if (
      (fallback !== null &&
        (value === null ||
          typeof value !== typeof fallback ||
          Array.isArray(value) !== Array.isArray(fallback))) ||
      (typeof value === "number" && !Number.isFinite(value))
    ) {
      return fallback;
    }
    return value as T;
  } catch {
    return fallback;
  }
}

export function writeJson<T>(key: string, value: T, kind: StorageKind = "local"): void {
  try {
    getStorage(kind).setItem(key, JSON.stringify(value));
  } catch {
    // Preferences remain usable when storage is blocked or full.
  }
}
