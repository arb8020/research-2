/**
 * mimir API client — talks to the Python webui server.
 */

export interface TreeData {
  files: string[];
  touched: Record<string, string[]>;
  branch: string;
}

export interface FileData {
  path: string;
  content: string;
}

export interface AtHit {
  branch: string;
  ranges: [number, number][];
  age_hours: number;
  worktree: string | null;
  line_in_branch: number | null;
}

export interface AtResult {
  path: string;
  hits: AtHit[];
  branches_scanned: number;
}

export interface DiffData {
  diff: string;
  ref: string | null;
  range: string | null;
}

async function json<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

export async function fetchTree(): Promise<TreeData> {
  return json("/api/tree");
}

export async function fetchFile(path: string, ref?: string): Promise<FileData> {
  const params = new URLSearchParams({ path });
  if (ref) params.set("ref", ref);
  return json(`/api/file?${params}`);
}

export async function fetchDiff(ref?: string, range?: string): Promise<DiffData> {
  const params = new URLSearchParams();
  if (ref) params.set("ref", ref);
  if (range) params.set("range", range);
  return json(`/api/diff?${params}`);
}

export async function fetchAt(
  path: string,
  start?: number,
  end?: number
): Promise<AtResult | null> {
  const params = new URLSearchParams({ path });
  if (start != null) params.set("start", String(start));
  if (end != null) params.set("end", String(end));
  const data = await json<{ at: AtResult | null }>(`/api/at?${params}`);
  return data.at;
}

/* ── annotate mode ─────────────────────────────────────────────── */

export interface MessageSummary {
  index: number;
  preview: string;
}

export interface AnnotateTarget {
  mode: "browse" | "diff" | "message";
  label: string;
  paths: string[];
  diff_ref: string | null;
  message_text: string | null;
  messages?: MessageSummary[];
}

export async function fetchMessage(index: number): Promise<{ index: number; text: string; preview: string }> {
  return json(`/api/message?index=${index}`);
}

export interface AnnotationData {
  file: string;
  start_line: number;
  end_line: number;
  side?: string | null;
  text: string;
  original_text?: string;
}

export async function fetchAnnotateTarget(): Promise<AnnotateTarget> {
  return json("/api/annotate/target");
}

export async function submitAnnotations(annotations: AnnotationData[]): Promise<void> {
  const res = await fetch("/api/annotate/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ annotations }),
  });
  if (!res.ok) throw new Error(`submit failed: ${res.status}`);
}
