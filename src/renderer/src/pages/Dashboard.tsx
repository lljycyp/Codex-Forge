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

export function Dashboard({ appState, profiles, runCommand }: DashboardProps) {
  const [selectedProfileName, setSelectedProfileName] = useState<string | null>(null);
  const readyProfiles = profiles.slice(0, 5);
  const activeProfile =
    profiles.find((profile) => profile.name === selectedProfileName) ??
    profiles.find((profile) => profile.running) ??
    profiles[0];

  return (
    <div className="dashboard-page">
      <div className="metric-grid">
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
      <div className="dashboard-workbench">
        <section className="dashboard-panel account-panel">
          <div className="panel-heading">
            <strong>常用账号</strong>
            <span>最多显示 5 个</span>
          </div>
          <div className="account-card-list">
            {readyProfiles.length ? (
              readyProfiles.map((profile) => (
                <button
                  key={profile.name}
                  type="button"
                  className={profile.name === activeProfile?.name ? "account-card active" : "account-card"}
                  onClick={() => setSelectedProfileName(profile.name)}
                >
                  <span className="account-avatar">{profile.name.slice(0, 1)}</span>
                  <span className="account-card-body">
                    <span className="account-card-head">
                      <span className="account-card-name">{profile.name}</span>
                      <Tag color={profile.running ? "green" : "default"}>{profile.running ? "运行中" : "就绪"}</Tag>
                    </span>
                  </span>
                </button>
              ))
            ) : (
              <div className="dashboard-empty">
                <Empty description="暂无账号" />
              </div>
            )}
          </div>
        </section>

        <section className="dashboard-panel detail-panel">
          <div className="detail-hero">
            <div>
              <div className="detail-title">{activeProfile ? `${activeProfile.name} ${activeProfile.running ? "正在运行" : "已就绪"}` : "暂无账号"}</div>
              <div className="detail-copy">
                {activeProfile
                  ? "程序副本、账号目录和同步入口集中在这里，减少高频操作来回跳转。"
                  : "新增账号后，可在这里快速启动并查看目录健康状态。"}
              </div>
            </div>
            <div className="detail-actions">
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

          <div className="detail-stat-grid">
            <div className="detail-stat">
              <span>程序副本</span>
              <strong>{activeProfile?.portableCodexExists ? "已准备" : "待准备"}</strong>
            </div>
            <div className="detail-stat">
              <span>账号目录</span>
              <strong>{activeProfile?.profileDirExists ? "可读取" : "需处理"}</strong>
            </div>
            <div className="detail-stat">
              <span>CodexHome</span>
              <strong>{activeProfile?.codexHomeExists ? "正常" : "缺失"}</strong>
            </div>
          </div>

          <div className="status-table">
            <div className="status-row head">
              <span>检查项</span>
              <span>状态</span>
              <span>说明</span>
              <span>操作</span>
            </div>
            <div className="status-row">
              <span>商店版路径</span>
              <span>{appState.codexExists ? "已识别" : "未识别"}</span>
              <span>{appState.codexVersion || "暂无版本"}</span>
              <span>设置</span>
            </div>
            <div className="status-row">
              <span>账号根目录</span>
              <span>{appState.profileRootExists ? "可读取" : "需处理"}</span>
              <Tooltip title={appState.profileRoot || "未设置"} placement="topLeft">
                <span className="table-path">{appState.profileRoot || "未设置"}</span>
              </Tooltip>
              <span>打开</span>
            </div>
            <div className="status-row">
              <span>会话同步</span>
              <span>{appState.sessionSyncEnabled ? "已开启" : "未开启"}</span>
              <span>实验性功能</span>
              <span>设置</span>
            </div>
            <div className="status-row">
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
