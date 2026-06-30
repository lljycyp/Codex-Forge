import type { ViewKey, ViewMeta } from "../types";

export const viewMeta: Record<ViewKey, ViewMeta> = {
  dashboard: {
    title: "账号控制台",
    description: "独立环境、独立数据目录、独立程序副本"
  },
  profiles: {
    title: "账号管理",
    description: "新增、启动、改名、删除和打开账号目录"
  },
  settings: {
    title: "启动器设置",
    description: "配置 Codex 程序路径、账号根目录和同步开关"
  },
  diagnostics: {
    title: "诊断报告",
    description: "检查配置、路径、程序副本、账号目录和同步状态"
  }
};

export const diagnosticBasicLabels: Record<string, string> = {
  configPath: "配置文件路径",
  configExists: "配置文件是否存在",
  lastGoodBackupExists: "最近可用备份是否存在",
  previousGoodBackupExists: "上一次可用备份是否存在",
  profileRoot: "账号根目录",
  profileRootWritable: "账号根目录是否可写",
  codexPath: "Codex 程序路径",
  codexExists: "Codex 程序是否存在",
  codexVersion: "Codex 版本",
  defaultEnvPath: "默认环境变量文件路径",
  defaultEnvExists: "默认环境变量文件是否存在",
  profileCount: "账号数量",
  sessionSyncEnabled: "会话同步是否开启",
  memorySyncEnabled: "记忆同步是否开启"
};
