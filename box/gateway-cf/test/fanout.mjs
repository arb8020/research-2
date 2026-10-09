// Proves SSE fan-out: 2 concurrent readers, producer over POST and websocket, reconnect with Last-Event-ID,
// ring wrap -> gap notice. Prints fan-out latency (producer send -> reader receive).
// Usage: BASE=http://localhost:8797 node test/fanout.mjs
import { api, assert, BASE, PRODUCER_BASE, machineSocket, pct, push, sleep, sse } from "./lib.mjs";

const S = `fanout-${Date.now()}`;
console.log("readers", BASE, "producer", PRODUCER_BASE, "session", S);

const a = sse(`/sessions/${S}/events`);
const b = sse(`/sessions/${S}/events`);
await Promise.all([a.ready, b.ready]);

// 1) POST producer: 20 log lines, timed one at a time.
const sent = new Map();
const lat = [];
const waitFor = (reader, text) =>
  new Promise((res) => {
    const t = setInterval(() => {
      const e = reader.events.find((x) => x.data.text === text);
      if (e) { clearInterval(t); res(e); }
    }, 1);
  });
for (let i = 0; i < 20; i++) {
  const text = `post line ${i}`;
  const t0 = performance.now();
  await push(S, [{ kind: "log", stream: "stdout", text }]);
  const [ea, eb] = await Promise.all([waitFor(a, text), waitFor(b, text)]);
  lat.push(ea.at - t0, eb.at - t0);
  sent.set(text, t0);
}
console.log(`POST->SSE latency ms: p50=${pct(lat, 50).toFixed(1)} p90=${pct(lat, 90).toFixed(1)} max=${Math.max(...lat).toFixed(1)}`);

// 2) Reader b drops; machine websocket pushes 30 more lines while b is away.
const bLast = b.lastId;
b.close();
const ws = await machineSocket(S);
const wsLat = [];
for (let i = 0; i < 30; i++) {
  const text = `ws line ${i}`;
  const t0 = performance.now();
  ws.send(JSON.stringify({ kind: "log", stream: "stdout", text }));
  const e = await waitFor(a, text);
  wsLat.push(e.at - t0);
}
console.log(`WS->SSE latency ms: p50=${pct(wsLat, 50).toFixed(1)} p90=${pct(wsLat, 90).toFixed(1)} max=${Math.max(...wsLat).toFixed(1)}`);

// 3) b reconnects with Last-Event-ID and must get exactly the 30 missed lines, in order, then live ones.
const b2 = sse(`/sessions/${S}/events`, { lastId: bLast });
await b2.ready;
await push(S, [{ kind: "log", stream: "stdout", text: "after reconnect" }]);
await waitFor(b2, "after reconnect");
await waitFor(a, "after reconnect");
const replayed = b2.events.map((e) => e.data.text);
assert(replayed.length === 31, `reconnect replay count 31 (got ${replayed.length})`);
assert(replayed.slice(0, 30).every((t, i) => t === `ws line ${i}`), "replayed lines in order, none duplicated");
const aTexts = a.events.map((e) => e.data.text);
assert(aTexts.length === 51, `reader a saw all 51 live events (got ${aTexts.length})`);
const ids = a.events.map((e) => e.id);
assert(ids.every((x, i) => i === 0 || x === ids[i - 1] + 1), "event ids are contiguous");

// 4) Ring wrap: push > RING_SIZE events, reconnect from id 1 -> gap notice + only the last RING_SIZE.
const RING = 1000;
const batch = Array.from({ length: 1100 }, (_, i) => ({ kind: "log", stream: "stdout", text: `bulk ${i}` }));
const { last_seq } = await push(S, batch);
const c = sse(`/sessions/${S}/events`, { lastId: 1 });
await c.ready;
await sleep(500);
const gap = c.events[0];
assert(gap.id == null && /replay gap: \d+ events dropped/.test(gap.data.text), `gap notice: "${gap.data.text}"`);
assert(c.events.length - 1 === RING, `ring replay holds exactly ${RING} (got ${c.events.length - 1})`);
assert(c.lastId === last_seq, "ring replay ends at the latest seq");

const st = await api("GET", `/sessions/${S}`);
console.log("status", JSON.stringify(st.body));
ws.close();
for (const r of [a, b2, c]) r.close();
process.exit(0);
