// Proves the DO kernel proxy: (1) websocket to a public echo origin, (2) Jupyter Server REST + kernel websocket
// behind a cloudflared quick tunnel, with the Jupyter token injected by the DO. Compares direct vs via gateway.
// Usage: JUPYTER_URL=https://x.trycloudflare.com JUPYTER_TOKEN=... node test/proxy.mjs
import WebSocket from "ws";
import { api, assert, BASE, pct } from "./lib.mjs";

const N = Number(process.env.N ?? 30);
const fmt = (xs) => `p50=${pct(xs, 50).toFixed(1)} p90=${pct(xs, 90).toFixed(1)} min=${Math.min(...xs).toFixed(1)} ms (n=${xs.length})`;
const wsUrl = (http) => http.replace(/^http/, "ws");

// Messages are queued from the start: a banner can arrive in the same read as the 101 and fire before `await` resumes.
function openWs(url, headers = {}) {
  const ws = new WebSocket(url, { headers });
  ws.queue = [];
  ws.waiters = [];
  ws.on("message", (m) => (ws.waiters.length ? ws.waiters.shift()(m) : ws.queue.push(m)));
  ws.next = () => new Promise((r) => (ws.queue.length ? r(ws.queue.shift()) : ws.waiters.push(r)));
  return new Promise((res, rej) => {
    ws.once("open", () => res(ws));
    ws.once("error", rej);
    ws.once("unexpected-response", (_req, r) => rej(new Error(`ws upgrade ${r.statusCode} on ${url}`)));
  });
}

async function setUpstream(session, url, token) {
  const r = await api("POST", `/sessions/${session}/upstream`, { url, token });
  assert(r.status === 200, `upstream set for ${session}: kernel.url=${r.body.status?.kernel?.url}`);
  return r.body.status.kernel.url;
}

// ---- 1) echo origin ----
async function echoRtts(url, skipFirst) {
  const ws = await openWs(url);
  const rtts = [];
  if (skipFirst) await ws.next(); // echo.websocket.org sends a banner first
  for (let i = 0; i < N; i++) {
    const t0 = performance.now();
    ws.send(`ping ${i}`);
    const got = String(await ws.next());
    if (got !== `ping ${i}`) throw new Error(`echo mismatch: ${got}`);
    rtts.push(performance.now() - t0);
  }
  ws.close();
  return rtts;
}

const ECHO = process.env.ECHO_URL ?? "https://echo.websocket.org";
const sEcho = `proxy-echo-${Date.now()}`;
const echoKernel = await setUpstream(sEcho, ECHO);
const viaEcho = await echoRtts(wsUrl(echoKernel) + "/", true);
const directEcho = await echoRtts(wsUrl(ECHO) + "/", true);
console.log(`echo direct     RTT ${fmt(directEcho)}`);
console.log(`echo via DO     RTT ${fmt(viaEcho)}`);

// ---- 2) Jupyter Server ----
const JURL = process.env.JUPYTER_URL;
const JTOK = process.env.JUPYTER_TOKEN;
if (!JURL) { console.log("JUPYTER_URL unset; skipping jupyter"); process.exit(0); }

async function jupyter(label, base, token) {
  const auth = token ? { authorization: `token ${token}` } : {};
  const t0 = performance.now();
  const st = await fetch(`${base}/api/status`, { headers: auth });
  const restMs = performance.now() - t0;
  assert(st.ok, `${label}: GET /api/status ${st.status} in ${restMs.toFixed(0)} ms`);
  const kr = await fetch(`${base}/api/kernels`, { method: "POST", headers: { ...auth, "content-type": "application/json" }, body: "{}" });
  const kernel = await kr.json();
  assert(kr.ok && kernel.id, `${label}: POST /api/kernels -> ${kernel.id}`);
  const tWs = performance.now();
  // Browser-shaped: token in the query (EventSource/WebSocket can't set headers). Via the gateway it's a placeholder.
  const ws = await openWs(`${wsUrl(base)}/api/kernels/${kernel.id}/channels?token=${token ?? "via-gateway"}`);
  const wsOpenMs = performance.now() - tWs;
  const session = crypto.randomUUID();
  const run = (code) =>
    new Promise((res) => {
      const msg_id = crypto.randomUUID();
      const out = [];
      const t = performance.now();
      const on = (raw) => {
        const m = JSON.parse(String(raw));
        if (m.parent_header?.msg_id !== msg_id) return;
        if (m.msg_type === "stream") out.push(m.content.text);
        if (m.channel === "shell" && m.msg_type === "execute_reply") {
          ws.off("message", on);
          res({ ms: performance.now() - t, out: out.join(""), status: m.content.status });
        }
      };
      ws.on("message", on);
      ws.send(JSON.stringify({
        header: { msg_id, session, username: "spike", msg_type: "execute_request", version: "5.3", date: new Date().toISOString() },
        parent_header: {}, metadata: {}, channel: "shell", buffers: [],
        content: { code, silent: false, store_history: false, user_expressions: {}, allow_stdin: false, stop_on_error: true },
      }));
    });
  const first = await run("import os; print('pid', os.getpid())");
  assert(first.status === "ok" && first.out.startsWith("pid"), `${label}: kernel ran code over ws: ${first.out.trim()}`);
  const shell = await run("!echo shell-ok");
  assert(shell.out.includes("shell-ok"), `${label}: IPython ! shell works`);
  const rtts = [];
  for (let i = 0; i < N; i++) rtts.push((await run(`print(${i})`)).ms);
  ws.close();
  await fetch(`${base}/api/kernels/${kernel.id}`, { method: "DELETE", headers: auth });
  console.log(`${label}: rest ${restMs.toFixed(0)} ms, ws open ${wsOpenMs.toFixed(0)} ms, execute RTT ${fmt(rtts)}`);
  return rtts;
}

const sJ = `proxy-jupyter-${Date.now()}`;
const jKernel = await setUpstream(sJ, JURL, JTOK);
// Without the DO-injected token Jupyter must refuse: check the proxy really is the one authenticating.
const noTok = await fetch(`${JURL}/api/kernels`);
assert(noTok.status === 403 || noTok.status === 401, `jupyter direct without token refused (${noTok.status})`);
if (process.env.JUPYTER_LOCAL) await jupyter("jupyter localhost   ", process.env.JUPYTER_LOCAL, JTOK);
await jupyter("jupyter direct tunnel", JURL, JTOK);
await jupyter("jupyter via DO      ", jKernel, null);
process.exit(0);
