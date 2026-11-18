import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [vue()],
  server: {
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
