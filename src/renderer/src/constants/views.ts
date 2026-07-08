import type { ViewKey, ViewMeta } from "../types";

export function getViewMeta(t: (text: string) => string): Record<ViewKey, ViewMeta> {
  return {
  home: {
    title: t("首页"),
    description: t("查看账号、运行模式和当前配置状态")
  },
  profiles: {
    title: t("账号管理"),
    description: t("保存当前账号资料、切换账号、改名、删除和打开目录")
  },
  instructions: {
    title: t("指令模板"),
    description: t("管理自定义指令模板，启用后写入当前 Codex 配置")
  },
  toml: {
    title: t("TOML 配置"),
    description: t("查看和编辑当前生效的 Codex config.toml")
  },
  settings: {
    title: t("Forge 设置"),
    description: t("配置账号资料根目录")
  }
  };
}
