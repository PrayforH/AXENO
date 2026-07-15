import { getHarnessServerConfig, type HarnessServerConfig } from "./server-config";

const PROXY_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "x-accel-buffering",
] as const;

function identityHeaders(config: HarnessServerConfig) {
  const headers = new Headers(config.identityHeaders);
  headers.set("Content-Type", "application/json");
  return headers;
}

function responseHeaders(upstream: Response) {
  const headers = new Headers();
  for (const name of PROXY_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

export async function proxyToHarness(
  request: Request,
  path: string,
  fetcher: typeof fetch = fetch,
) {
  const config = getHarnessServerConfig();
  const url = `${config.apiUrl}${path}`;
  try {
    const upstream = await fetcher(url, {
      method: request.method,
      headers: identityHeaders(config),
      body:
        request.method !== "GET" && request.method !== "HEAD"
          ? await request.text()
          : undefined,
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders(upstream),
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "harness_unavailable",
          message: "Harness API 当前不可用，请确认本地服务已经启动。",
        },
      },
      { status: 502 },
    );
  }
}
