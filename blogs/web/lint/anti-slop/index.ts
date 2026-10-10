// Vendored subset of https://github.com/dmmulroy/anti-slop (commit c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b,
// src/index.ts), trimmed to the four rules this repo enables.
// Copyright (c) 2026 Dillon Mulroy. MIT License: see ./LICENSE.
import { eslintCompatPlugin } from "@oxlint/plugins";

import { noChainedTypeAssertionsRule } from "./rules/no-chained-type-assertions.ts";
import { noConditionalEmptyObjectSpreadRule } from "./rules/no-conditional-empty-object-spread.ts";
import { noUnsafeDictionaryTypeRule } from "./rules/no-unsafe-dictionary-type.ts";
import { noWidenThenAssertRule } from "./rules/no-widen-then-assert.ts";

const antiSlopPlugin = eslintCompatPlugin({
	meta: { name: "anti-slop" },
	rules: {
		"no-chained-type-assertions": noChainedTypeAssertionsRule,
		"no-conditional-empty-object-spread": noConditionalEmptyObjectSpreadRule,
		"no-unsafe-dictionary-type": noUnsafeDictionaryTypeRule,
		"no-widen-then-assert": noWidenThenAssertRule,
	},
});

export default antiSlopPlugin;
