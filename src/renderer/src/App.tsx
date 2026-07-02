import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Layout, Typography, message } from "antd";
import { RefreshCw, Settings, ShieldCheck } from "lucide-react";
import { AppLayout } from "./components/AppLayout";
import { viewMeta } from "./constants/views";
import { invokeLauncher } from "./api/launcher";
import { Profiles } from "./pages/Profiles";
import { SettingsPage } from "./pages/SettingsPage";
import type { AppState, ProfileSummary, RunCommand, ViewKey } from "./types";

const { Content } = Layout;

const emptyState: AppState = {
  codexCommandAvailable: false,
  activeAuthPath: "",
  activeAuthExists: false,
  activeConfigPath: "",
  activeConfigExists: false,
  activeProfile: "",
  profileRoot: "",
  profileRootExists: false,
  profileCount: 0,
  runningCount: 0
};

const refreshDelayCommands = new Set(["launch_profile", "stop_profile"]);

export default function App() {
  const [activeView, setActiveView] = useState<ViewKey>("profiles");
  const [appState, setAppState] = useState<AppState>(emptyState);
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [refreshingView, setRefreshingView] = useState<ViewKey | null>(null);
  const [commandingView, setCommandingView] = useState<ViewKey | null>(null);
  const [taskText, setTaskText] = useState("就绪");
  const contentRef = useRef<HTMLDivElement | null>(null);
  const activeViewRef = useRef<ViewKey>("profiles");
  const refreshTokenRef = useRef(0);
  const commandTokenRef = useRef(0);

  useEffect(() => {
    activeViewRef.current = activeView;
  }, [activeView]);

  const refresh = useCallback(async (view?: ViewKey | null) => {
    const refreshToken = view ? ++refreshTokenRef.current : refreshTokenRef.current;
    if (view) {
      setRefreshingView(view);
    }
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
      if (view && refreshTokenRef.current === refreshToken) {
        setRefreshingView(null);
      }
    }
  }, []);

  useEffect(() => {
    refresh(null);
  }, [refresh]);

  const runCommand = useCallback<RunCommand>(
    async (command, payload, successText = "操作完成", options) => {
      const commandToken = ++commandTokenRef.current;
      const sourceView = activeViewRef.current;
      const shouldBlockView = options?.blocking !== false;
      const shouldRefreshAfter = options?.refreshAfter !== false;
      if (shouldBlockView) {
        setCommandingView(sourceView);
      }
      setTaskText("正在执行...");
      try {
        await invokeLauncher(command, payload);
        if (refreshDelayCommands.has(command)) {
          await new Promise((resolve) => setTimeout(resolve, 800));
        }
        message.success(successText);
        setTaskText(successText);
        if (shouldRefreshAfter) {
          await refresh(null);
        }
      } catch (error) {
        const text = error instanceof Error ? error.message : "操作失败";
        setTaskText(text);
        message.error(text);
      } finally {
        if (shouldBlockView && commandTokenRef.current === commandToken) {
          setCommandingView(null);
        }
      }
    },
    [refresh]
  );

  const menuItems = useMemo(
    () => [
      { key: "profiles" as const, label: "账号", icon: <ShieldCheck size={18} /> },
      { key: "settings" as const, label: "设置", icon: <Settings size={18} /> }
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
    },
    []
  );

  const refreshButton = (
    <Button
      className="shrink-0 rounded-card border-shell-line font-bold text-[#344054] hover:!border-brand-600 hover:!text-brand-600"
      icon={<RefreshCw size={16} />}
      loading={refreshingView === activeView}
      onClick={() => refresh(activeView)}
    >
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
      topbarAction={
        activeView === "profiles" ? refreshButton : null
      }
    >
      <Content
        ref={contentRef}
        className="m-0 min-h-0 flex-auto overflow-auto rounded-none border-0 bg-white px-[30px] py-[22px] shadow-none"
      >
        <div className="mb-4 hidden max-[960px]:block [&_h3]:!mb-1 [&_h3]:!leading-tight">
          <Typography.Title level={3}>{currentView.title}</Typography.Title>
          <Typography.Text type="secondary">{currentView.description}</Typography.Text>
        </div>
        {activeView === "profiles" ? (
          <Profiles
            profiles={profiles}
            runningCount={appState.runningCount}
            runCommand={runCommand}
            loading={commandingView === "profiles"}
          />
        ) : null}
        {activeView === "settings" ? (
          <SettingsPage appState={appState} runCommand={runCommand} />
        ) : null}
      </Content>
    </AppLayout>
  );
}
