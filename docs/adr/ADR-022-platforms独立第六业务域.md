# ADR-022 · platforms 独立为第六业务域

- 状态：已采纳（2026-11-17 用户裁决，修正 ADR-018 表名纪律下的账户域托管方案）
- 背景：平台（连接器家族）被多域引用——账户名册挂 `platform_code`、调度按
  平台排班、执行按平台路由端口；ADR-018 链把平台册寄居账户域造成引用倒挂，
  后续拼装与跨域对接都别扭。
- 决策：
  1. `platforms` 独立为第六业务域：core = `butler_core/platforms/`
     （domain/ports/usecases 三件套，PlatformEntry + PlatformRepository +
     SyncPlatforms），engine = `butler_engine/platforms/sqlite.py`。
  2. 表名按 ADR-018 纪律：`plat_platform`（acc_platform RENAME 幂等自迁移）；
     分域生成视图新增 `data/sql/platforms.sql`。
  3. 域间引用恒等式不变：其它域只持 `platform_code` 字符串，不 import 本域；
     端侧 `/platforms` 契约与路由不变（SDK/前端零改动）。
- 后果：core 域依赖机检（域→shared）覆盖新包；A2-04 §2.2 平台册节回收进
  A2-09；域图（A1-05）五个业务域 → 六个。
