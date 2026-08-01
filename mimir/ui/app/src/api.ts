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
