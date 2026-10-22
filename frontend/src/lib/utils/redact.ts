const REDACTED = "[REDACTED]";

const SENSITIVE_PARAM_RE =
  /([?&][^=\s&;]*(?:api[_-]?key|apikey|authorization|client[_-]?secret|password|passwd|pwd|private[_-]?key|secret|token|cookie|session|jwt|csrf|x-plex-token)[^=\s&;]*=)[^&\s]+/gi;
const SENSITIVE_KV_RE =
  /\b([^=\s:,;{}]*(?:api[_-]?key|apikey|authorization|client[_-]?secret|password|passwd|pwd|private[_-]?key|secret|token|cookie|set-cookie|session|jwt|csrf|x-plex-token)[^=\s:,;{}]*\s*[:=]\s*)("[^"]+"|'[^']+'|[^&,\s;}]+)/gi;
const AUTH_HEADER_RE =
  /\b(authorization\s*[:=]\s*)((?:bearer|basic)\s+|mediabrowser\s+token="?)[^",\s;}]+"?/gi;
const URL_USERINFO_RE = /\b([a-z][a-z0-9+.-]*:\/\/)([^/@\s]+)@/gi;
const PLEX_DIRECT_URL_RE = /\b(https?:\/\/)[^\s/?#"'<]+\.plex\.direct(?::\d+)?[^\s"'<]*/gi;
const JWT_RE = /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g;

export function supportReference(value: string | null | undefined): string | null {
  return value && /^[\w-]{1,64}$/.test(value) ? value : null;
}

export function redactText(value: unknown): string {
  return String(value)
    .replace(SENSITIVE_PARAM_RE, `$1${REDACTED}`)
    .replace(AUTH_HEADER_RE, `$1$2${REDACTED}`)
    .replace(SENSITIVE_KV_RE, `$1${REDACTED}`)
    .replace(JWT_RE, REDACTED)
    .replace(PLEX_DIRECT_URL_RE, `$1${REDACTED}.plex.direct`)
    .replace(URL_USERINFO_RE, `$1${REDACTED}@`);
}
