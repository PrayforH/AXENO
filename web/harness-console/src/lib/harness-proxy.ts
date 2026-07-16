import type { HarnessServerConfig } from "./server-config";

const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "x-accel-buffering",
];

function upstreamHeaders(request: Request, config: HarnessServerConfig) {
  const headers = new Headers({
    ...config.identityHeaders,
    ...config.serviceHeaders,
  });
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
    const upstream = await fetcher(url, {
      method: request.method,
      headers: upstreamHeaders(request, config),
      body: await requestBody(request),
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders(upstream),
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
