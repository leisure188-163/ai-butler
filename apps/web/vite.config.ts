import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  // 路径别名（2026-11-20 按业务域分包）：域内互相引用一律走 @/ 绝对路径，
  // 文件在域内/域间搬动不必再改一串 ../（相对路径正是前端目录越理越乱的原因）。
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    // 固定绑 IPv4：Windows 下 Node 默认 host=localhost 会解析到 ::1，
    // 导致 `http://127.0.0.1:5173` 连接被拒（2026-11-19 实测），而项目
    // 文档与浏览器收藏用的都是 127.0.0.1。
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      // 设置页「接口文档」按同源派生（/docs），dev 下转发给主控 server；
      // /openapi.json 是 Swagger UI 自己拉取的契约源，必须一起代理
      "/docs": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/openapi.json": { target: "http://127.0.0.1:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist" },
});
