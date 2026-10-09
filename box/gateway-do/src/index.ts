// The Worker: box/CONTRACT-gateway.md for variants (B) and (C), one deployment, chosen by path prefix:
//   gateway = https://<worker>/b   (B) do-owns: OwnerDO is the session; it calls the relay RELAY_B
//   gateway = https://<worker>/c   (C) fanout:  the relay RELAY_C (= variant A) owns control; FanoutDO fans out
// Stateless itself: CORS, routing, checking push keys, and (C) forwarding control ops to the relay.
//
//   POST /{v}/sessions               -> relay POST /sessions; then the session's DO learns of it (created)
//   GET  /{v}/sessions/{id}          -> (B) OwnerDO.get        (C) relay
//   POST /{v}/sessions/{id}/end      -> (B) OwnerDO.end        (C) relay
//   GET  /{v}/sessions/{id}/events   -> the DO's SSE (?token=id:secret)
//   POST /{v}/sessions/{id}/push     -> the DO (X-Push-Key = HMAC(PUSH_SECRET, "push:" + id)): relay + machine forwarder
//   *    /b/sessions/{id}/kernel/... -> OwnerDO's token-gated Jupyter proxy (HTTP + websocket)

import { json, sha256hex } from "./hub";
import { relayFetch } from "./relay";
import { BadInput, parseCreated, parseCreateToken, type Env } from "./types";

export { FanoutDO } from "./fanout-do";
export { OwnerDO } from "./owner-do";

const ROUTE = /^\/([bc])\/sessions(?:\/(s-[0-9a-f]{12})(\/.*)?)?$/;
const MAX_CREATE_BYTES = 8 * 1024; // the relay's MAX_BODY

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "content-type, last-event-id, x-box-token",
};

function withCors(resp: Response): Response {
  if (resp.status === 101) return resp; // websocket upgrade: nothing to add
  const out = new Response(resp.body, resp);
  for (const [k, v] of Object.entries(CORS)) out.headers.set(k, v);
  return out;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    const url = new URL(req.url);
    if (url.pathname === "/health") return withCors(json({ ok: true }));
    const m = url.pathname.match(ROUTE);
    if (!m) return withCors(json({ error: `no route ${req.method} ${url.pathname}` }, 404));
    const [, v, id, rest = ""] = m;
    try {
      return withCors(await route(req, env, v as "b" | "c", id, rest, gatewayOrigin(req, url, v)));
    } catch (e) {
      if (e instanceof BadInput) return withCors(json({ error: e.message }, 400));
      throw e;
    }
  },
} satisfies ExportedHandler<Env>;

async function route(req: Request, env: Env, v: "b" | "c", id: string | undefined, rest: string, origin: string): Promise<Response> {
  const m = req.method;
  if (id === undefined) return m === "POST" ? create(req, env, v, origin) : json({ error: `no route ${m} /sessions` }, 404);
  if (rest === "/push" && m === "POST") return push(req, env, v, id);
  if (rest === "/events" || rest.startsWith("/kernel")) return stub(env, v, id).fetch(req);
  const auth = req.headers.get("x-box-token") ?? "";
  if (v === "c" && ((rest === "" && m === "GET") || (rest === "/end" && m === "POST"))) {
    return relayFetch(env.RELAY_C, `/sessions/${id}${rest}`, { method: m, headers: { "x-box-token": auth } });
  }
  const owner = env.OWNER.get(env.OWNER.idFromName(id));
  if (rest === "" && m === "GET") return reply(await owner.get(auth));
  if (rest === "/end" && m === "POST") return reply(await owner.end(auth));
  return json({ error: `no route ${m} /sessions/{id}${rest}` }, 404);
}

// Both variants make the machine through the relay; then the DO named by the new session id learns
// who may read it ((C): a digest) or takes the session over ((B): the token itself).
async function create(req: Request, env: Env, v: "b" | "c", origin: string): Promise<Response> {
  const body = await req.text();
  if (body.length > MAX_CREATE_BYTES) throw new BadInput(`body over ${MAX_CREATE_BYTES} bytes`);
  const token = parseCreateToken(JSON.parse(body));
  const headers: Record<string, string> = { "content-type": "application/json" };
  const pageOrigin = req.headers.get("origin");
  if (pageOrigin) headers.origin = pageOrigin; // the relay lets this origin reach Jupyter directly ((C))
  const r = await relayFetch(v === "b" ? env.RELAY_B : env.RELAY_C, "/sessions", { method: "POST", headers, body });
  if (r.status !== 202) return r;
  const relayText = await r.text();
  const made = parseCreated(JSON.parse(relayText));
  const digest = await sha256hex(`${token.id}:${token.secret}`);
  if (v === "c") {
    await env.FANOUT.get(env.FANOUT.idFromName(made.session_id)).created(digest);
    return new Response(relayText, { status: 202, headers: { "content-type": "application/json" } });
  }
  const owner = env.OWNER.get(env.OWNER.idFromName(made.session_id));
  const status = await owner.created({ id: made.session_id, origin, token, digest, gpu: made.status.gpu });
  return json({ session_id: made.session_id, status }, 202);
}

async function push(req: Request, env: Env, v: "b" | "c", id: string): Promise<Response> {
  if (!(await pushKeyOk(env.PUSH_SECRET, id, req.headers.get("x-push-key") ?? ""))) return json({ error: "bad push key" }, 401);
  const r = await stub(env, v, id).push(await req.text());
  return "error" in r ? json(r, 400) : json(r);
}

async function pushKeyOk(secretHex: string, id: string, got: string): Promise<boolean> {
  const secret = new Uint8Array(secretHex.match(/../g)!.map((h) => parseInt(h, 16)));
  const key = await crypto.subtle.importKey("raw", secret, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`push:${id}`)));
  const want = new TextEncoder().encode([...mac].map((b) => b.toString(16).padStart(2, "0")).join(""));
  const have = new TextEncoder().encode(got);
  return have.length === want.length && crypto.subtle.timingSafeEqual(have, want);
}

function stub(env: Env, v: "b" | "c", id: string) {
  return v === "b" ? env.OWNER.get(env.OWNER.idFromName(id)) : env.FANOUT.get(env.FANOUT.idFromName(id));
}

const reply = (r: { code: number; body: unknown }): Response => json(r.body, r.code);

// This gateway's public base for one variant, e.g. https://box-gateway-do.x.workers.dev/b. Behind a
// TLS-terminating tunnel (cloudflared -> wrangler dev) the Worker sees http://: trust the forwarded proto.
function gatewayOrigin(req: Request, url: URL, v: string): string {
  const proto = req.headers.get("x-forwarded-proto");
  return `${proto ? `${proto}://${url.host}` : url.origin}/${v}`;
}
