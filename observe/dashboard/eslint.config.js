import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import base from "./eslint.base.js"; // canonical copy: ~/dotfiles/lint/eslint.base.js

export default tseslint.config(
  ...base,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { tsconfigRootDir: import.meta.dirname },
    },
    settings: {
      "import/resolver": {
        typescript: {
          project: ["./tsconfig.app.json", "./tsconfig.server.json"],
          noWarnOnMultipleProjects: true,
        },
      },
    },
    rules: {
      // Architectural boundaries, enforced mechanically.
      "import/no-restricted-paths": [
        "error",
        {
          basePath: import.meta.dirname,
          zones: [
            {
              target: "./src/core",
              from: "./src/app",
              message: "core/ must not import app/ — core is below the UI.",
            },
            {
              target: "./src/core",
              from: "./src/views",
              message:
                "core/ must not import views/ — views are discovered, not imported.",
            },
            {
              target: "./src/views",
              from: "./src/app",
              message:
                "views/ must not import app/ — a view never sees the chrome.",
            },
            {
              // The server may reach down into core/ (parseLine, to index runs)
              // but never up into the UI.
              target: "./server",
              from: "./src/app",
              message: "server/ must not import src/app/ — the server has no UI.",
            },
            {
              target: "./server",
              from: "./src/views",
              message: "server/ must not import src/views/ — the server has no UI.",
            },
          ],
        },
      ],
    },
  },
  {
    // The server runs on Bun, not in the browser.
    files: ["server/**/*.ts"],
    languageOptions: {
      globals: { ...globals.node, Bun: "readonly" },
    },
  },
  {
    files: ["**/*.tsx"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-hooks/exhaustive-deps": "error",
    },
  },
  {
    files: ["eslint.config.js", "eslint.base.js", "vite.config.ts", "vitest.config.ts"],
    ...tseslint.configs.disableTypeChecked,
  },
);
