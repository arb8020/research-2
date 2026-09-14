/**
 * Parse unified diff (git diff output) into per-file chunks.
 */

export interface DiffFile {
  oldPath: string;
  newPath: string;
  /** Raw diff text for this file (including headers, hunks, +/- lines) */
  rawDiff: string;
  additions: number;
  deletions: number;
}

export function parseUnifiedDiff(patch: string): DiffFile[] {
  const lines = patch.split("\n");
  const files: DiffFile[] = [];

  let currentStart = -1;
  let currentOldPath = "";
  let currentNewPath = "";
  let additions = 0;
  let deletions = 0;

  function flush(endIndex: number) {
    if (currentStart < 0) return;
    // Trim trailing empty lines
    let end = endIndex;
    while (end > currentStart && lines[end - 1] === "") end--;
    files.push({
      oldPath: currentOldPath,
      newPath: currentNewPath,
      rawDiff: lines.slice(currentStart, end).join("\n"),
      additions,
      deletions,
    });
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    if (line.startsWith("diff --git ")) {
      flush(i);
      currentStart = i;
      additions = 0;
      deletions = 0;
      const match = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      currentOldPath = match?.[1] ?? "";
      currentNewPath = match?.[2] ?? "";
      continue;
    }

    if (currentStart >= 0) {
      if (line.startsWith("+") && !line.startsWith("+++")) additions++;
      if (line.startsWith("-") && !line.startsWith("---")) deletions++;
    }
  }

  flush(lines.length);
  return files;
}
