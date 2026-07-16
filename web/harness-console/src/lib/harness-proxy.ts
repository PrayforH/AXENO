import type { HarnessServerConfig } from "./server-config";
import {
  ACCESS_COOKIE,
  appendClearedSessionCookies,
  appendSessionCookies,
  readCookie,
  refreshSession,
} from "./auth-session";

const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "etag",
  "x-accel-buffering",
  "x-agent-content-sha256",
  "x-agent-package-sha256",
];

function upstreamHeaders(
  request: Request,
  config: HarnessServerConfig,
  accessToken = readCookie(request, ACCESS_COOKIE),
) {
  const headers = new Headers({
    ...config.serviceHeaders,
  });
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  for (const name of ["accept", "content-type", "last-event-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

function responseHeaders(upstream: Response) {
  const headers = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

async function requestBody(request: Request): Promise<ArrayBuffer | undefined> {
  if (request.method === "GET" || request.method === "HEAD") return undefined;
  const body = await request.arrayBuffer();
  return body.byteLength ? body : undefined;
}

function unavailableResponse() {
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

async function forward(
  request: Request,
  url: string,
  config: HarnessServerConfig,
  fetcher: typeof fetch,
) {
  try {
    const body = await requestBody(request);
    let upstream = await fetcher(url, {
      method: request.method,
      headers: upstreamHeaders(request, config),
      body,
      cache: "no-store",
      signal: request.signal,
    });
    let refreshed;
    if (upstream.status === 401) {
      refreshed = await refreshSession(request, config, fetcher);
      if (refreshed) {
        upstream = await fetcher(url, {
          method: request.method,
          headers: upstreamHeaders(request, config, refreshed.access_token),
          body,
          cache: "no-store",
          signal: request.signal,
        });
      }
    }
    const headers = responseHeaders(upstream);
    if (refreshed) appendSessionCookies(headers, refreshed, config);
    else if (upstream.status === 401) appendClearedSessionCookies(headers, config);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers,
    });
  } catch {
    return unavailableResponse();
  }
}

export async function proxyAguiRequest(
  request: Request,
  config: HarnessServerConfig,
  fetcher: typeof fetch = fetch,
  path = "",
) {
  const url = new URL(config.aguiUrl);
  if (path) {
    url.pathname = `${url.pathname.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
    url.search = "";
  }
  return forward(request, url.toString(), config, fetcher);
}

export async function proxyInputArtifactRequest(
  request: Request,
  config: HarnessServerConfig,
  fetcher: typeof fetch = fetch,
) {
  return forward(
    request,
    `${config.apiUrl}/v1/input-artifacts`,
    config,
    fetcher,
  );
}

export async function proxyStudioRequest(
  request: Request,
  config: HarnessServerConfig,
  fetcher: typeof fetch = fetch,
  path = "",
) {
  const url = new URL(
    `${config.apiUrl}/v1/studio${path ? `/${path.replace(/^\//, "")}` : ""}`,
  );
  url.search = new URL(request.url).search;
  return forward(request, url.toString(), config, fetcher);
}
