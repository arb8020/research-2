// Calls to the Python relay (box/gateway/relay.py): (C) forwards the reader's control ops to it as they
// are; (B)'s DO calls it with the token it holds, to create and end machines (the box SDK lives there:
// Modal's API is gRPC, which a Worker can't speak).

import type { ModalToken } from "./types";

export const RELAY_TIMEOUT_MS = 90_000; // POST /end waits for the supervisor to say it ended (relay: CLOSE_TIMEOUT_S 60)

export async function relayFetch(base: string, path: string, init: RequestInit): Promise<Response> {
  return fetch(`${base.replace(/\/$/, "")}${path}`, { ...init, signal: AbortSignal.timeout(RELAY_TIMEOUT_MS) });
}

// (B): a call with the session's token; {code, body} (body parsed if JSON, else the text).
export async function relayCall(base: string, method: string, path: string, token: ModalToken): Promise<{ code: number; body: unknown }> {
  const r = await relayFetch(base, path, { method, headers: { "x-box-token": `${token.id}:${token.secret}` } });
  const text = await r.text();
  try {
    return { code: r.status, body: JSON.parse(text) };
  } catch {
    return { code: r.status, body: text };
  }
}
