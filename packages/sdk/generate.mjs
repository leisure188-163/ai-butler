// 契约流水线：server OpenAPI → openapi.json → schema.d.ts + openapi.sha256
// 不再要求"先起 server"：直接从 FastAPI app 对象导出（verify 同款 import 路径）。
// sha256 口径与 verify_project.check_sdk_freshness 完全一致：
//   hash(json.dumps(app.openapi()) + "\n")   ← print 自带换行，两者必须同串
import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const DUMP = [
  "import json, hashlib",
  "from server.main import app",
  "payload = json.dumps(app.openapi())",
  "print(payload)",
  "print(hashlib.sha256((payload + chr(10)).encode('utf-8')).hexdigest())",
].join("; ");

const out = execSync(`uv run python -c "${DUMP}"`, {
  stdio: ["ignore", "pipe", "inherit"],
}).toString();
// python 输出固定两行：payload\nfingerprint\n（payload 无缩进，单行 JSON）
const nl = out.indexOf("\n");
const payload = out.slice(0, nl);
const fingerprint = out.slice(nl + 1).trim();

writeFileSync("src/gen/openapi.json", payload + "\n");
execSync("npx openapi-typescript src/gen/openapi.json -o src/gen/schema.d.ts", {
  stdio: "inherit",
});
writeFileSync("src/gen/openapi.sha256", fingerprint + "\n");

console.log("SDK 生成完成 → packages/sdk/src/gen/{schema.d.ts, openapi.sha256}");
console.log(`契约指纹: ${fingerprint}`);
