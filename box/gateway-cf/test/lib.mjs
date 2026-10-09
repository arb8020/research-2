// Tiny test clients: SSE reader (fetch stream, supports Last-Event-ID) and a machine producer (POST + websocket).
import WebSocket from "ws";

export const BASE = process.env.BASE ?? "http://localhost:8797";
// The machine may reach the gateway by a different URL (e.g. a cloudflared quick tunnel) than readers do.
export const PRODUCER_BASE = process.env.PRODUCER_BASE ?? BASE;
export const MACHINE_KEY = process.env.MACHINE_KEY ?? "dev-machine-key";

// Returns {events, close, lastId}; onEvent(ev, id) is called per data frame.
export function sse(path, { lastId, onEvent } = {}) {
  const ctrl = new AbortController();
  const state = { events: [], lastId: lastId ?? null, close: () => ctrl.abort() };
  state.ready = (async () => {
    const headers = lastId != null ? { "last-event-id": String(lastId) } : {};
    const resp = await fetch(BASE + path, { headers, signal: ctrl.signal });
    if (!resp.ok) throw new Error(`sse ${resp.status}`);
    state.done = (async () => {
      const dec = new TextDecoder();
      let buf = "";
      try {
        for await (const chunk of resp.body) {
          buf += dec.decode(chunk, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, i);
            buf = buf.slice(i + 2);
            let id = null, data = null;
            for (const line of block.split("\n")) {
              if (line.startsWith("id: ")) id = Number(line.slice(4));
              else if (line.startsWith("data: ")) data = JSON.parse(line.slice(6));
            }
            if (data == null) continue;
            if (id != null) state.lastId = id;
            state.events.push({ id, data, at: performance.now() });
            onEvent?.(data, id);
          }
        }
      } catch (e) {
        if (e.name !== "AbortError") throw e;
      }
    })();
  })();
  return state;
}

export async function push(session, events) {
  const body = events.map((e) => JSON.stringify(e)).join("\n");
  const r = await fetch(`${PRODUCER_BASE}/sessions/${session}/events`, {
    method: "POST",
    headers: { "x-machine-key": MACHINE_KEY, "content-type": "application/x-ndjson" },
    body,
  });
  if (!r.ok) throw new Error(`push ${r.status} ${await r.text()}`);
  return r.json();
}

export function machineSocket(session) {
  const ws = new WebSocket(`${PRODUCER_BASE.replace(/^http/, "ws")}/sessions/${session}/machine`, {
    headers: { "x-machine-key": MACHINE_KEY },
  });
  return new Promise((res, rej) => {
    ws.on("open", () => res(ws));
    ws.on("error", rej);
  });
}

export async function api(method, path, body, headers = {}) {
  const r = await fetch(BASE + path, {
    method,
    headers: { "x-machine-key": MACHINE_KEY, "content-type": "application/json", ...headers },
    body: body == null ? undefined : JSON.stringify(body),
  });
  const text = await r.text();
  try {
    return { status: r.status, body: JSON.parse(text) };
  } catch {
    return { status: r.status, body: text };
  }
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const pct = (xs, p) => {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor((p / 100) * s.length))];
};
export function assert(cond, msg) {
  if (!cond) {
    console.error("FAIL:", msg);
    process.exit(1);
  }
  console.log("ok:", msg);
}
