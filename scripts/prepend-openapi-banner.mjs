import { readFileSync, writeFileSync } from "node:fs";

const target = "openapi/waterfall_v1.yaml";
const banner =
  "# GENERATED FILE — do not edit directly.\n" +
  "# Edit sources under openapi/spec/ and run: npm run openapi:bundle\n\n";

const content = readFileSync(target, "utf8");
if (!content.startsWith(banner)) {
  writeFileSync(target, banner + content);
}
