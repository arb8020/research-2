# Bug: `mimir annotate` opens wrong file

## Reproduction

```bash
cd /Users/chiraagbalu/silares_stuff/obol/worktrees/scorer-unification
mimir annotate docs/concepts/grading.md
```

Browser opens but does not show the correct file. `plannotator annotate docs/concepts/grading.md` works correctly from the same directory.

## Expected

Browser opens with `docs/concepts/grading.md` loaded for annotation.

## Actual

Browser opens to a different file or blank state.

## Environment

- Working directory: a git worktree (`worktrees/scorer-unification`)
- File exists at the path
- `plannotator annotate` works as expected with the same arguments

## Possible cause

Worktree path resolution — mimir may resolve the file relative to the main checkout rather than the worktree.
