// Files in the connected sandbox through Jupyter's Contents API (the same server and token as the kernel). The page
// reads and writes workspace files this way rather than through the kernel: ~15 ms a round trip on Modal, and it
// works while a long cell keeps the kernel busy. Cross-origin PUT with a JSON body is preflighted; the relay's
// Jupyter flags allow it (spike/workspace-cells exp1).
import { kernelAddress } from "./kernel";

export class ContentsError extends Error {}

function url(path: string, query = ""): string {
  const address = kernelAddress();
  if (address === undefined) throw new ContentsError("contents: not connected");
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `${address.url}/api/contents/${encoded}?token=${encodeURIComponent(address.token)}${query}`;
}

async function put(path: string, body: Record<string, unknown>): Promise<void> {
  const res = await fetch(url(path), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new ContentsError(`PUT ${path}: ${String(res.status)} ${await res.text()}`);
}

// The file's text, or undefined if there is no such file.
export async function readText(path: string): Promise<string | undefined> {
  const res = await fetch(url(path, "&type=file&format=text&content=1"));
  if (res.status === 404) return undefined;
  if (!res.ok) throw new ContentsError(`GET ${path}: ${String(res.status)} ${await res.text()}`);
  const body: unknown = await res.json();
  if (typeof body !== "object" || body === null || !("content" in body) || typeof body.content !== "string") {
    throw new ContentsError(`GET ${path}: expected {content: string}, got ${JSON.stringify(body).slice(0, 200)}`);
  }
  return body.content;
}

export const writeText = (path: string, text: string): Promise<void> => put(path, { type: "file", format: "text", content: text });

export function writeBytes(path: string, bytes: Uint8Array): Promise<void> {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return put(path, { type: "file", format: "base64", content: btoa(binary) });
}

export const makeDir = (path: string): Promise<void> => put(path, { type: "directory" });
