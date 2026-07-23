import type { ViewKey, ViewMeta } from "../types";

export function getViewMeta(t: (text: string) => string): Record<ViewKey, ViewMeta> {
  return {
  home: {
    title: t("首页"),
    description: t("查看运行状态与当前工作环境")
  },
  profiles: {
    title: t("账号管理"),
    description: t("查看运行实例、选择账号并管理账号环境")
  },
  workspace: {
    title: t("环境工作台"),
    description: t("管理额度历史、健康检查、MCP、Skills、会话与启动环境")
  },
  instructions: {
    title: t("指令模板"),
    description: t("管理自定义指令模板，启用后写入当前 Codex 配置")
  },
  toml: {
    title: t("TOML 配置"),
    description: t("查看和编辑当前生效的 Codex config.toml")
  },
  skin: {
    title: t("Codex 换肤"),
    description: t("管理 Codex 外观、背景主题与显示构图")
  },
  settings: {
    title: t("Forge 设置"),
    description: t("配置账号资料根目录")
  }
  };
}
