import { Button, Empty, Tag, Tooltip } from "antd";
import { Play, Square } from "lucide-react";
import { useState } from "react";
import { Metric } from "../components/Metric";
import type { AppState, ProfileSummary, RunCommand } from "../types";

type DashboardProps = {
  appState: AppState;
  profiles: ProfileSummary[];
  runCommand: RunCommand;
};

const accountCardBaseClass =
  "grid min-h-[60px] w-full grid-cols-[36px_minmax(0,1fr)] items-center gap-2.5 rounded-[9px] border border-transparent bg-slate-50 p-[11px] text-left text-gray-900 hover:border-brand-600/20 hover:bg-[#f2f7f6]";

const statusRowClass =
  "grid min-h-11 grid-cols-[1fr_0.72fr_1.1fr_0.48fr] items-center border-b border-[#ecf1f6] px-[13px] text-[12.5px] last:border-b-0";

export function Dashboard({ appState, profiles, runCommand }: DashboardProps) {
  const [selectedProfileName, setSelectedProfileName] = useState<string | null>(null);
  const readyProfiles = profiles.slice(0, 5);
  const activeProfile =
    profiles.find((profile) => profile.name === selectedProfileName) ??
    profiles.find((profile) => profile.running) ??
    profiles[0];

  return (
    <div className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4 max-[1100px]:h-auto">
      <div className="grid grid-cols-4 gap-3 max-[960px]:grid-cols-2">
        <Metric title="账号数量" value={appState.profileCount} note="当前可用账号总数" statusText="正常" />
        <Metric title="运行中" value={appState.runningCount} note="正在运行的窗口" statusText="活跃" />
        <Metric
          title="程序状态"
          value={appState.codexExists ? "已识别" : "未识别"}
          note={appState.codexVersion || "等待识别版本"}
          statusText={appState.codexExists ? "可用" : "处理"}
          statusTone={appState.codexExists ? "green" : "amber"}
        />
        <Metric
          title="配置健康"
          value={appState.profileRootExists ? "可读取" : "需处理"}
          note="账号根目录状态"
          statusText={appState.profileRootExists ? "正常" : "异常"}
          statusTone={appState.profileRootExists ? "green" : "amber"}
        />
      </div>
      <div className="grid min-h-0 grid-cols-[330px_minmax(0,1fr)] gap-4 max-[1100px]:grid-cols-1">
        <section className="min-h-0 overflow-hidden rounded-card border border-shell-line bg-white shadow-none">
          <div className="flex h-[52px] items-center justify-between border-b border-[#ecf1f6] px-4">
            <strong className="text-sm">常用账号</strong>
            <span className="text-xs font-extrabold text-brand-600">最多显示 5 个</span>
          </div>
          <div className="grid gap-2 p-3">
            {readyProfiles.length ? (
              readyProfiles.map((profile) => (
                <button
                  key={profile.name}
                  type="button"
                  className={
                    profile.name === activeProfile?.name
                      ? `${accountCardBaseClass} border-brand-600/30 bg-brand-50`
                      : accountCardBaseClass
                  }
                  onClick={() => setSelectedProfileName(profile.name)}
                >
                  <span
                    className={
                      profile.name === activeProfile?.name
                        ? "grid h-9 w-9 place-items-center rounded-panel bg-brand-600 text-sm font-black text-white"
                        : "grid h-9 w-9 place-items-center rounded-panel bg-slate-200 text-sm font-black text-slate-600"
                    }
                  >
                    {profile.name.slice(0, 1)}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center justify-between gap-2 text-[13.5px] font-extrabold [&_.ant-tag]:me-0 [&_.ant-tag]:shrink-0">
                      <span className="min-w-0 truncate">{profile.name}</span>
                      <Tag color={profile.running ? "green" : "default"}>
                        {profile.running ? "运行中" : "就绪"}
                      </Tag>
                    </span>
                  </span>
                </button>
              ))
            ) : (
              <div className="grid min-h-[220px] place-items-center">
                <Empty description="暂无账号" />
              </div>
            )}
          </div>
        </section>

        <section className="grid min-h-0 grid-rows-[auto_auto_1fr] gap-3.5 overflow-hidden rounded-card border border-shell-line bg-white p-4 shadow-none">
          <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 rounded-panel border border-[#cbe8e2] bg-[#f8fbff] bg-detail-gradient p-4">
            <div>
              <div className="text-lg font-black">
                {activeProfile ? `${activeProfile.name} ${activeProfile.running ? "正在运行" : "已就绪"}` : "暂无账号"}
              </div>
              <div className="mt-[7px] max-w-xl text-[12.5px] leading-relaxed text-[#526071]">
                {activeProfile
                  ? "程序副本、账号目录和同步入口集中在这里，减少高频操作来回跳转。"
                  : "新增账号后，可在这里快速启动并查看目录健康状态。"}
              </div>
            </div>
            <div className="flex flex-wrap justify-end gap-2 [&_.ant-btn]:rounded-card [&_.ant-btn]:font-bold">
              <Button
                type="primary"
                danger={activeProfile?.running}
                icon={activeProfile?.running ? <Square size={15} /> : <Play size={15} />}
                disabled={!activeProfile}
                onClick={() =>
                  activeProfile &&
                  runCommand(
                    activeProfile.running ? "stop_profile" : "launch_profile",
                    { name: activeProfile.name },
                    activeProfile.running ? "已停止账号" : "已启动账号"
                  )
                }
              >
                {activeProfile?.running ? "停止" : "启动"}
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-3 gap-2.5">
            <div className="rounded-[9px] border border-shell-line bg-white p-[13px]">
              <span className="block text-[11.5px] text-shell-muted">程序副本</span>
              <strong className="mt-2 block text-sm">{activeProfile?.portableCodexExists ? "已准备" : "待准备"}</strong>
            </div>
            <div className="rounded-[9px] border border-shell-line bg-white p-[13px]">
              <span className="block text-[11.5px] text-shell-muted">账号目录</span>
              <strong className="mt-2 block text-sm">{activeProfile?.profileDirExists ? "可读取" : "需处理"}</strong>
            </div>
            <div className="rounded-[9px] border border-shell-line bg-white p-[13px]">
              <span className="block text-[11.5px] text-shell-muted">CodexHome</span>
              <strong className="mt-2 block text-sm">{activeProfile?.codexHomeExists ? "正常" : "缺失"}</strong>
            </div>
          </div>

          <div className="min-h-0 overflow-hidden rounded-[9px] border border-shell-line">
            <div className={`${statusRowClass} min-h-[38px] bg-slate-50 font-extrabold text-shell-muted`}>
              <span>检查项</span>
              <span>状态</span>
              <span>说明</span>
              <span>操作</span>
            </div>
            <div className={statusRowClass}>
              <span>商店版路径</span>
              <span>{appState.codexExists ? "已识别" : "未识别"}</span>
              <span>{appState.codexVersion || "暂无版本"}</span>
              <span>设置</span>
            </div>
            <div className={statusRowClass}>
              <span>账号根目录</span>
              <span>{appState.profileRootExists ? "可读取" : "需处理"}</span>
              <Tooltip title={appState.profileRoot || "未设置"} placement="topLeft">
                <span className="mt-1 block truncate text-[11.5px] text-shell-muted">
                  {appState.profileRoot || "未设置"}
                </span>
              </Tooltip>
              <span>打开</span>
            </div>
            <div className={statusRowClass}>
              <span>会话同步</span>
              <span>{appState.sessionSyncEnabled ? "已开启" : "未开启"}</span>
              <span>实验性功能</span>
              <span>设置</span>
            </div>
            <div className={statusRowClass}>
              <span>记忆同步</span>
              <span>{appState.memorySyncEnabled ? "已开启" : "未开启"}</span>
              <span>实验性功能</span>
              <span>设置</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
