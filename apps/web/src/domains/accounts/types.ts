/**
 * 账户域 DTO（对应 server routes/accounts.py 的 Out 模型）：账户册、凭据、体检证据、会话。
 */
import type { WithSignal } from "@/shared/types/base";
import type { contract } from "@/shared/types/contract";

export type AccountDeleted = contract["AccountDeletedOut"];

export type CredentialItem = WithSignal<contract["CredentialOut"]>;

/** 嵌套字段同样要窄化：credentials 里的凭据行也是 UI 消费面（signal 必须是 Signal） */
export type AccountItem =
  Omit<contract["AccountOut"], "signal" | "credentials"> & {
    signal: WithSignal<contract["AccountOut"]>["signal"];
    credentials: CredentialItem[];
  };

export type EvidenceItem = contract["EvidenceOut"];

/** 会话清单（R5-S1）：kind/level = core 词表原样，UI 只渲染不判类 */
export type SessionItem = contract["SessionOut"];
export type SessionsScan = contract["SessionsScanOut"];
