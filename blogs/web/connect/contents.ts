import { kernelAddress } from "./kernel";

export class ContentsError extends Error {}

function url(path: string, query = ""): string {
  const address = kernelAddress();
  if (address === undefined) throw new ContentsError("contents: not connected");
  if (path.split("/").some((p) => p.startsWith("."))) {
    throw new ContentsError(`contents: ${path} is hidden; the Contents API refuses dot paths with no CORS headers, so the page would see only "Failed to fetch"`);
  }
  const encoded = path.split("/").map(encodeURIComponent).join("/");
  return `${address.url}/api/contents/${encoded}?token=${encodeURIComponent(address.token)}${query}`;
}

type Model = { type: "file"; format: "text" | "base64"; content: string } | { type: "directory" };

async function put(path: string, body: Model): Promise<void> {
  const res = await fetch(url(path), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new ContentsError(`PUT ${path}: ${String(res.status)} ${await res.text()}`);
}

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
