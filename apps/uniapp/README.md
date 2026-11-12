# uniapp 端（微信小程序 + App 一码双投）

1. HBuilderX 打开本目录，manifest.json 填小程序 AppID。
2. src/api/request.ts 里配置 API_BASE（线上需 ICP 备案 + 微信后台 request 合法域名）。
3. 运行 → 运行到小程序模拟器；发行 → 原生 App 云打包。
4. 页面骨架与 apps/web 同构：列表 + 新增表单，统一走 SDK 请求层。
