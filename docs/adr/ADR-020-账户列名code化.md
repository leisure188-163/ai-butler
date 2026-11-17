# ADR-020 · accounts 列名 code 化（account_code / platform_code / account_name）

- 状态：已采纳（2026-11-17 用户裁决）
- 背景：accounts v3（ADR-019）落地后，用户裁决把三个业务列名改为更明确的
  编码/名称后缀风格：`account_key`→`account_code`、`platform`→`platform_code`、
  `display_name`→`account_name`。
- 决策：
  1. 列名与 domain 字段、契约（AccountOut / usage radar 行）、web 消费面同步
     改名；概念术语「平台 / Platform」不变（连接器家族、路由 `/platforms`、
     PlatformOut 仍用 platform），只改账户域这一层的列/字段/契约。
  2. 索引改名：`uq_accounts_platform_code_key (platform_code, account_code)`、
     `idx_accounts_platform_code (platform_code)`。
  3. 老库自迁移追加 v3 早期形状分支：存在旧列名且新列名缺失时
     `ALTER TABLE RENAME COLUMN` 一轮改齐（幂等）；v1/v2 重建路径不变。
- 后果：规范 id 编址 `{platform}:{account_code}` 不变（id 内容无迁移）；
  契约为破坏性字段改名，SDK 与 web 同步重生成。
