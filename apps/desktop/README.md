# Electron 桌面壳（Python sidecar 模式）

## 双模式

- **在线/开发**：`WEB_URL=http://localhost:5173 npm start`（或指向线上站点）。
- **离线**：Electron 拉起 PyInstaller 打包的 `server-sidecar.exe`（API + web 静态资源同源伺服），stdout 读取 `SIDECAR_PORT` 后加载页面。

## 打包步骤

```bash
# 1. 构建前端并复制给 sidecar
pnpm build:web && cp -r ../web/dist ../server/web_dist
# 2. 打包 sidecar（在 apps/server 下）
uv run pyinstaller --onefile --name server-sidecar --add-data "web_dist:web_dist" sidecar_entry.py
# 3. 放置产物并打包桌面壳
mkdir -p sidecar && cp dist/server-sidecar.exe sidecar/
npm run dist   # electron-builder，extraResources 已配置
```

## 何时选 Electron（对比 pywebview）

需要 electron-updater 自动更新、系统托盘、跨 OS 一致的 Chromium 渲染、成熟崩溃上报时选它；
代价是安装包 100-200MB、内存 ~150-300MB、Node+Python 双工具链。纯 Python 团队/轻量工具用 pywebview。
