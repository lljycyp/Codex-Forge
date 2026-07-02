import type { ViewKey, ViewMeta } from "../types";

export const viewMeta: Record<ViewKey, ViewMeta> = {
  profiles: {
    title: "账号管理",
    description: "保存当前账号资料、切换账号、改名、删除和打开目录"
  },
  settings: {
    title: "切换器设置",
    description: "配置账号资料根目录"
  }
};
