import { vi } from "vitest";

export interface FetchCall {
  url: string;
  init: RequestInit;
}

async function fetchCall(input: RequestInfo | URL, init: RequestInit = {}): Promise<FetchCall> {
  const request =
    input instanceof Request ? input : new Request(new URL(String(input), location.origin), init);
  const url = new URL(request.url, location.origin);
  return {
    url: `${url.pathname}${url.search}`,
    init: {
      ...init,
      body: init.body ?? (request.body ? await request.clone().text() : undefined),
      headers: Object.fromEntries(new Headers(init.headers ?? request.headers).entries()),
      method: init.method ?? request.method,
    },
  };
}

function headers(init?: ResponseInit): HeadersInit | undefined {
  if (!init?.headers) return undefined;
  return init.headers;
}

export function mockFetch(
  response: unknown,
  init: ResponseInit = {},
): { calls: FetchCall[]; fetchMock: ReturnType<typeof vi.fn> } {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, requestInit?: RequestInit) => {
    calls.push(await fetchCall(input, requestInit));
    return new Response(init.status === 204 ? null : JSON.stringify(response), {
      status: init.status ?? 200,
      statusText: init.statusText,
      headers:
        init.status === 204
          ? headers(init)
          : {
              "Content-Type": "application/json",
              ...(headers(init) as Record<string, string> | undefined),
            },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

export function mockFetchSequence(responses: Array<{ body: unknown; init?: ResponseInit }>): {
  calls: FetchCall[];
  fetchMock: ReturnType<typeof vi.fn>;
} {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, requestInit?: RequestInit) => {
    calls.push(await fetchCall(input, requestInit));
    const next = responses.shift() ?? { body: {}, init: { status: 500 } };
    return new Response(next.init?.status === 204 ? null : JSON.stringify(next.body), {
      status: next.init?.status ?? 200,
      statusText: next.init?.statusText,
      headers:
        next.init?.status === 204
          ? headers(next.init)
          : {
              "Content-Type": "application/json",
              ...(headers(next.init) as Record<string, string> | undefined),
            },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

/**
 * Answer each request by its path, without the query: a value is the JSON
 * body of a 200 response, a function builds the whole response. Any other
 * path answers 404.
 */
export function mockFetchRoutes(routes: Record<string, unknown>): {
  calls: FetchCall[];
  fetchMock: ReturnType<typeof vi.fn>;
} {
  const calls: FetchCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, requestInit?: RequestInit) => {
    const call = await fetchCall(input, requestInit);
    calls.push(call);
    const route = routes[new URL(call.url, location.origin).pathname];
    if (route === undefined) return Response.json({ detail: "Not Found" }, { status: 404 });
    return typeof route === "function"
      ? (route as (call: FetchCall) => Response)(call)
      : Response.json(route);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}
