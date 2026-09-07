import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  // E4-17 (#157): same McCabe cyclomatic-complexity metric and threshold (15) as
  // the backend's Ruff C90 gate (#58), the sole complexity metric normative for
  // this frontend. Any `// eslint-disable-next-line complexity` beyond the ones
  // already documented in this codebase must carry a comment linking to the
  // tracking issue for its decomposition -- see README.md's "Complexité" section.
  {
    rules: {
      complexity: ["error", 15],
    },
  },
]);

export default eslintConfig;
