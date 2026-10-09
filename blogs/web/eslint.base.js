// Canonical TypeScript lint rules. Encodes ~/.codex/skills/typescript-best-practices
// and docs/synthesis/CODING_STANDARDS.md mechanically.
//
// Consumers: copy this file into the repo next to eslint.config.js and spread it:
//
//   import base from "./eslint.base.js";
//   export default tseslint.config(...base, { /* project-specific: import zones, globals */ });
//
// Project-specific things do NOT belong here: import/no-restricted-paths zones,
// tsconfig paths, per-directory globals. `lint/sync.sh` reports drift.
//
// Peer deps (pin exact versions in the consumer):
//   @eslint/js typescript-eslint eslint-plugin-import eslint-import-resolver-typescript
//   eslint-plugin-react-hooks (only if React)

import js from "@eslint/js";
import tseslint from "typescript-eslint";
import importPlugin from "eslint-plugin-import";

export const rules = {
  // Sum types with a visible switch; exhaustiveness via `never` is not optional.
  "@typescript-eslint/switch-exhaustiveness-check": "error",
  "@typescript-eslint/no-explicit-any": "error",
  // No `as` anywhere. Validate at the boundary, then narrow. `as const` stays legal —
  // the rule treats const assertions separately.
  "@typescript-eslint/consistent-type-assertions": ["error", { assertionStyle: "never" }],
  "@typescript-eslint/consistent-type-imports": "error",
  // Bracket access is the honest spelling for an index signature: it is what makes
  // noUncheckedIndexedAccess add `| undefined`.
  "@typescript-eslint/dot-notation": ["error", { allowIndexSignaturePropertyAccess: true }],
  // Function signatures are the contract; make the return type visible.
  "@typescript-eslint/explicit-function-return-type": ["error", { allowExpressions: true }],
};

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { parserOptions: { projectService: true } },
    plugins: { import: importPlugin },
    rules,
  },
];
