/**
 * Parse unified diff (git diff output) into per-file old/new string pairs
 * that @codemirror/merge can consume.
 */

export interface DiffFile {
  oldPath: string;
  newPath: string;
  oldContent: string;
  newContent: string;
}

export function parseUnifiedDiff(patch: string): DiffFile[] {
  const lines = patch.split("\n");
  const files: DiffFile[] = [];
  let currentFile: {
    oldPath: string;
    newPath: string;
    oldLines: string[];
    newLines: string[];
  } | null = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // New file header
    if (line.startsWith("diff --git ")) {
      if (currentFile) {
        files.push({
          oldPath: currentFile.oldPath,
          newPath: currentFile.newPath,
          oldContent: currentFile.oldLines.join("\n"),
          newContent: currentFile.newLines.join("\n"),
        });
      }
      const match = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      currentFile = {
        oldPath: match?.[1] ?? "",
        newPath: match?.[2] ?? "",
        oldLines: [],
        newLines: [],
      };
      continue;
    }

    // Skip file metadata lines
    if (
      line.startsWith("--- ") ||
      line.startsWith("+++ ") ||
      line.startsWith("index ") ||
      line.startsWith("new file") ||
      line.startsWith("deleted file") ||
      line.startsWith("rename ") ||
      line.startsWith("similarity ") ||
      line.startsWith("Binary ")
    ) {
      continue;
    }

    // Hunk header — reset is handled by context/add/delete naturally
    if (line.startsWith("@@ ")) {
      // Parse line numbers to insert blank lines for gaps
      // For now, just continue — the content lines handle it
      continue;
    }

    if (!currentFile) continue;

    // Content lines
    if (line.startsWith("+")) {
      currentFile.newLines.push(line.slice(1));
    } else if (line.startsWith("-")) {
      currentFile.oldLines.push(line.slice(1));
    } else if (line.startsWith(" ")) {
      currentFile.oldLines.push(line.slice(1));
      currentFile.newLines.push(line.slice(1));
    }
    // "\ No newline at end of file" — skip
  }

  // Flush last file
  if (currentFile) {
    files.push({
      oldPath: currentFile.oldPath,
      newPath: currentFile.newPath,
      oldContent: currentFile.oldLines.join("\n"),
      newContent: currentFile.newLines.join("\n"),
    });
  }

  return files;
}
