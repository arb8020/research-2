// SSE fan-out: one hub per DO, one stream per connected reader.
// Not hibernation-friendly: an open SSE response keeps the DO in memory (fine on free plan; costs duration on paid).

import type { Stored } from "./event-log";

const enc = new TextEncoder();

export function frame(s: Stored): string {
  return `id: ${s.seq}\ndata: ${JSON.stringify(s.event)}\n\n`;
}

export class SseHub {
  private subs = new Set<WritableStreamDefaultWriter<Uint8Array>>();
  private heartbeat: ReturnType<typeof setInterval> | null = null;

  constructor(private heartbeatMs: number) {}

  get size(): number {
    return this.subs.size;
  }

  // Open a stream; `backlog` frames are written first (replay), then live events via broadcast().
  open(backlog: string): Response {
    const { readable, writable } = new TransformStream<Uint8Array, Uint8Array>();
    const w = writable.getWriter();
    this.subs.add(w);
    w.closed.catch(() => {}).finally(() => this.drop(w));
    this.write(w, `retry: 1000\n${backlog}`);
    this.ensureHeartbeat();
    return new Response(readable, {
      headers: { "content-type": "text/event-stream", "cache-control": "no-cache", "x-accel-buffering": "no" },
    });
  }

  broadcast(text: string): void {
    for (const w of this.subs) this.write(w, text);
  }

  closeAll(): void {
    for (const w of this.subs) w.close().catch(() => {});
    this.subs.clear();
  }

  private write(w: WritableStreamDefaultWriter<Uint8Array>, text: string): void {
    w.write(enc.encode(text)).catch(() => this.drop(w));
  }

  private drop(w: WritableStreamDefaultWriter<Uint8Array>): void {
    this.subs.delete(w);
    if (this.subs.size === 0 && this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }

  private ensureHeartbeat(): void {
    if (this.heartbeat) return;
    this.heartbeat = setInterval(() => this.broadcast(": hb\n\n"), this.heartbeatMs);
  }
}
