// Proves the DO deadline alarm fires: set deadline = now + IN_MS, wait for status ended/deadline on SSE.
// Usage: node test/alarm.mjs [in_ms]          (or SESSION=x WAIT=0 to only arm, for the restart test)
import { api, assert, BASE, sse } from "./lib.mjs";

const IN_MS = Number(process.argv[2] ?? 2000);
const S = process.env.SESSION ?? `alarm-${Date.now()}`;
const deadline = Date.now() + IN_MS;
const r = await api("POST", `/sessions/${S}/deadline`, { deadline });
assert(r.status === 200 && r.body.status.deadline === deadline, `armed deadline in ${IN_MS} ms on ${S} (${BASE})`);
if (process.env.WAIT === "0") process.exit(0);

const reader = sse(`/sessions/${S}/events`, { lastId: 0 });
await reader.ready;
const ended = await new Promise((res) => {
  const t = setInterval(() => {
    const e = reader.events.find((x) => x.data.kind === "status" && x.data.status.state === "ended");
    if (e) { clearInterval(t); res(e); }
  }, 5);
});
const late = Date.now() - deadline;
assert(ended.data.status.reason === "deadline", `status ended, reason=deadline, observed ${late} ms after deadline`);
const step = reader.events.find((x) => x.data.kind === "step");
console.log("gateway step:", step?.data.text);
reader.close();
process.exit(0);
