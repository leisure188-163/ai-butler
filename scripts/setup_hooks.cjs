// pnpm install 收尾自动启用提交信息钩子（任何失败都不阻断安装）
const { execSync } = require("child_process");

try {
  execSync("git config --local core.hooksPath .githooks", { stdio: "pipe" });
  console.log("已启用提交信息钩子（.githooks/commit-msg）");
} catch (e) {
  console.warn("跳过提交钩子启用（手动可跑 python scripts/install_hooks.py）: "
    + String(e.message).split("\n")[0]);
}
