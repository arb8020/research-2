// Worker entry: CORS + route /sessions/{id}/... to that session's Durable Object. Stateless.

import type { Env } from "./types";

export { SessionDO } from "./session-do";

const SESSION_PATH = /^\/sessions\/([A-Za-z0-9_-]{1,64})(\/.*)?$/;

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, DELETE, OPTIONS",
  "access-control-allow-headers": "content-type, authorization, last-event-id, x-box-token, x-machine-key",
};

function withCors(resp: Response): Response {
  if (resp.status === 101) return resp; // websocket upgrade: headers are immutable / irrelevant
  const out = new Response(resp.body, resp);
  for (const [k, v] of Object.entries(CORS)) out.headers.set(k, v);
  return out;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const url = new URL(req.url);
    if (url.pathname === "/health") return withCors(Response.json({ ok: true }));

    const m = url.pathname.match(SESSION_PATH);
    if (!m) return withCors(Response.json({ error: "not found" }, { status: 404 }));

    const fwd = new Request(req);
    fwd.headers.set("x-session-id", m[1]);
    // Behind a TLS-terminating tunnel (cloudflared -> wrangler dev) the Worker sees http://; trust the forwarded proto.
    const proto = req.headers.get("x-forwarded-proto");
    fwd.headers.set("x-gateway-origin", proto ? `${proto}://${url.host}` : url.origin);
    const stub = env.SESSION.get(env.SESSION.idFromName(m[1]));
    return withCors(await stub.fetch(fwd));
  },
} satisfies ExportedHandler<Env>;
