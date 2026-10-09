import tseslint from "typescript-eslint";
import base from "./eslint.base.js"; // canonical copy: ~/dotfiles/lint/eslint.base.js

export default tseslint.config(
  ...base,
  { ignores: ["build/**"] },
  {
    files: ["**/*.ts"],
    languageOptions: { parserOptions: { tsconfigRootDir: import.meta.dirname } },
  },
  {
    files: ["*.js"],
    ...tseslint.configs.disableTypeChecked,
  },
);
