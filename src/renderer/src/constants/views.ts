import type { ViewKey, ViewMeta } from "../types";

export const viewMeta: Record<ViewKey, ViewMeta> = {
  profiles: {
    title: "账号管理",
    description: "保存当前账号资料、切换账号、改名、删除和打开目录"
  },
  instructions: {
    title: "指令模板",
    description: "管理自定义指令模板，启用后写入当前 Codex 配置"
  },
  toml: {
    title: "TOML 配置",
    description: "查看和编辑当前生效的 Codex config.toml"
  },
  settings: {
    title: "Forge 设置",
    description: "配置账号资料根目录"
  }
};
