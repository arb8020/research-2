// Reverse proxy to an upstream origin (e.g. Jupyter Server behind a Modal / cloudflared tunnel).
// HTTP and websocket upgrades both go through fetch(): Workers hand back the upstream socket as resp.webSocket
// and returning that response to the client splices the two sockets together.

export interface Upstream {
  url: string; // http(s) base, e.g. https://abc.trycloudflare.com
  token?: string; // injected as `Authorization: token <t>` (Jupyter); the browser never sees it
}

export async function proxy(req: Request, up: Upstream, restPath: string): Promise<Response> {
  const src = new URL(req.url);
  const target = new URL(up.url.replace(/^ws/, "http"));
  target.pathname = target.pathname.replace(/\/$/, "") + restPath;
  target.search = src.search;

  const headers = new Headers(req.headers);
  headers.delete("host");
  // Jupyter rejects cross-origin websockets; the gateway is the gatekeeper, so drop the browser's Origin.
  headers.delete("origin");
  if (up.token) headers.set("authorization", `token ${up.token}`);

  const isWs = req.headers.get("upgrade")?.toLowerCase() === "websocket";
  return fetch(target.toString(), {
    method: req.method,
    headers,
    body: isWs || req.method === "GET" || req.method === "HEAD" ? undefined : req.body,
    redirect: "manual",
  });
}
