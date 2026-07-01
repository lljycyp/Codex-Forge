import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Layout, Typography, message } from "antd";
import { Activity, RefreshCw, Settings, ShieldCheck, Stethoscope } from "lucide-react";
import { AppLayout } from "./components/AppLayout";
import { viewMeta } from "./constants/views";
import { invokeLauncher } from "./api/launcher";
import { Dashboard } from "./pages/Dashboard";
import { Diagnostics } from "./pages/Diagnostics";
import { Profiles } from "./pages/Profiles";
import { SettingsPage } from "./pages/SettingsPage";
import type { AppState, DiagnosticsData, ProfileSummary, RunCommand, ViewKey } from "./types";

const { Content } = Layout;

const emptyState: AppState = {
  codexPath: "",
  codexExists: false,
  codexVersion: "",
  profileRoot: "",
  profileRootExists: false,
  profileCount: 0,
  runningCount: 0,
  sessionSyncEnabled: false,
  memorySyncEnabled: false
};

const refreshDelayCommands = new Set(["launch_profile", "stop_profile"]);

export default function App() {
  const [activeView, setActiveView] = useState<ViewKey>("dashboard");
  const [appState, setAppState] = useState<AppState>(emptyState);
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [diagnostics, setDiagnostics] = useState<DiagnosticsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [taskText, setTaskText] = useState("就绪");
  const contentRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [stateData, profileData] = await Promise.all([
        invokeLauncher<AppState>("get_app_state"),
        invokeLauncher<{ profiles: ProfileSummary[] }>("list_profiles")
      ]);
      setAppState(stateData);
      setProfiles(profileData.profiles);
      setTaskText("状态已刷新");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "刷新失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const loadDiagnostics = useCallback(async () => {
    setLoading(true);
    try {
      const data = await invokeLauncher<DiagnosticsData>("get_diagnostics");
      setDiagnostics(data);
      setTaskText("诊断已更新");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "诊断失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const runCommand = useCallback<RunCommand>(
    async (command, payload, successText = "操作完成") => {
      setLoading(true);
      setTaskText("正在执行...");
      try {
        await invokeLauncher(command, payload);
        if (refreshDelayCommands.has(command)) {
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
        message.success(successText);
        setTaskText(successText);
        await refresh();
      } catch (error) {
        const text = error instanceof Error ? error.message : "操作失败";
        setTaskText(text);
        message.error(text);
      } finally {
        setLoading(false);
      }
    },
    [refresh]
  );

  const menuItems = useMemo(
    () => [
      { key: "dashboard" as const, label: "控制台", icon: <Activity size={18} /> },
      { key: "profiles" as const, label: "账号", icon: <ShieldCheck size={18} /> },
      { key: "settings" as const, label: "设置", icon: <Settings size={18} /> },
      { key: "diagnostics" as const, label: "诊断", icon: <Stethoscope size={18} /> }
    ],
    []
  );
  const currentView = viewMeta[activeView];

  useEffect(() => {
    document.title = `${currentView.title} - Codex 多账号启动器`;
  }, [currentView.title]);

  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0 });
  }, [activeView]);

  const changeView = useCallback(
    (view: ViewKey) => {
      setActiveView(view);
      if (view === "diagnostics") {
        loadDiagnostics();
      }
    },
    [loadDiagnostics]
  );

  const refreshButton = (
    <Button className="topbar-action" icon={<RefreshCw size={16} />} loading={loading} onClick={refresh}>
      刷新
    </Button>
  );

  return (
    <AppLayout
      activeView={activeView}
      currentView={currentView}
      menuItems={menuItems}
      taskText={taskText}
      onChangeView={changeView}
      topbarAction={refreshButton}
    >
      <Content ref={contentRef} className="content">
        <div className="mobile-heading">
          <Typography.Title level={3}>{currentView.title}</Typography.Title>
          <Typography.Text type="secondary">{currentView.description}</Typography.Text>
        </div>
        {activeView === "dashboard" ? (
          <Dashboard appState={appState} profiles={profiles} runCommand={runCommand} />
        ) : null}
        {activeView === "profiles" ? (
          <Profiles profiles={profiles} runCommand={runCommand} loading={loading} />
        ) : null}
        {activeView === "settings" ? (
          <SettingsPage appState={appState} runCommand={runCommand} />
        ) : null}
        {activeView === "diagnostics" ? (
          <Diagnostics diagnostics={diagnostics} loadDiagnostics={loadDiagnostics} loading={loading} />
        ) : null}
      </Content>
    </AppLayout>
  );
}
