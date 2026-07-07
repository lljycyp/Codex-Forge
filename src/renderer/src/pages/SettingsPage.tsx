import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, message, Modal, Radio, Space, Switch } from "antd";
import { FolderOpen, Github, HardDrive, Info, Power, RefreshCw } from "lucide-react";
import type { AppState, RunCommand } from "../types";

type SettingsPageProps = {
  appState: AppState;
  runCommand: RunCommand;
};

function GiteeIcon({ size = 16 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 1024 1024"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <circle cx="512" cy="512" r="448" fill="#c71d23" />
      <path
        fill="#fff"
        d="M300 512c0-117 95-212 212-212h212v120H512a92 92 0 0 0 0 184h92v-72H484V412h240v312H512c-117 0-212-95-212-212Z"
      />
    </svg>
  );
}

export function SettingsPage({ appState, runCommand }: SettingsPageProps) {
  const [form] = Form.useForm();
  const [autoStartEnabled, setAutoStartEnabled] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const [autoStartLoading, setAutoStartLoading] = useState(false);
  const [checkUpdateLoading, setCheckUpdateLoading] = useState(false);
  const [launchModeLoading, setLaunchModeLoading] = useState(false);

  useEffect(() => {
    form.setFieldsValue({
      profileRoot: appState.profileRoot,
    });
  }, [appState, form]);

  useEffect(() => {
    let disposed = false;
    void window.launcherApi.getAppVersion?.()
      .then((version) => {
        if (!disposed) {
          setAppVersion(version);
        }
      })
      .catch(() => undefined);
    const loadAutoStartEnabled = async () => {
      if (!window.launcherApi.getAutoStartEnabled) {
        message.warning("请重启启动器后再使用开机自启设置");
        return;
      }
      try {
        const enabled = await window.launcherApi.getAutoStartEnabled();
        if (!disposed) {
          setAutoStartEnabled(enabled);
        }
      } catch (error) {
        if (!disposed) {
          message.error(error instanceof Error ? error.message : "读取开机自启状态失败");
        }
      }
    };
    void loadAutoStartEnabled();
    return () => {
      disposed = true;
    };
  }, []);

  const changeAutoStartEnabled = async (enabled: boolean) => {
    if (!window.launcherApi.setAutoStartEnabled) {
      message.warning("请重启启动器后再使用开机自启设置");
      return;
    }
    const previousValue = autoStartEnabled;
    setAutoStartEnabled(enabled);
    setAutoStartLoading(true);
    try {
      const savedValue = await window.launcherApi.setAutoStartEnabled(enabled);
      setAutoStartEnabled(savedValue);
      message.success(savedValue ? "已开启开机自启" : "已关闭开机自启");
    } catch (error) {
      setAutoStartEnabled(previousValue);
      message.error(error instanceof Error ? error.message : "保存开机自启设置失败");
    } finally {
      setAutoStartLoading(false);
    }
  };

  const checkForUpdates = async () => {
    if (!window.launcherApi.checkForUpdates) {
      message.warning("当前版本不支持手动检查更新，请重启后再试");
      return;
    }
    setCheckUpdateLoading(true);
    try {
      message.info("正在检查更新");
      await window.launcherApi.checkForUpdates();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "检查更新失败");
    } finally {
      setCheckUpdateLoading(false);
    }
  };

  const chooseProfileRoot = async () => {
    const selectedPath = await window.launcherApi.selectDirectory(
      appState.profileRoot || undefined,
    );
    if (!selectedPath) {
      return;
    }
    Modal.confirm({
      title: "更改账号资料位置",
      content: "将迁移整个账号资料根目录。迁移期间请先关闭正在运行的 Codex。",
      okText: "开始迁移",
      cancelText: "取消",
      onOk: async () => {
        form.setFieldsValue({ profileRoot: selectedPath });
        await runCommand(
          "set_profile_root",
          { profileRoot: selectedPath, asStorageLocation: true },
          "账号资料位置已更新",
        );
      },
    });
  };

  const saveLaunchMode = async (mode: "switch" | "multi") => {
    if (mode === appState.launchMode) {
      return;
    }
    setLaunchModeLoading(true);
    try {
      await runCommand(
        "set_launch_mode",
        { mode },
        mode === "multi" ? "已切换到多开隔离模式" : "已切换到账号切换模式",
        { blocking: false },
      );
    } finally {
      setLaunchModeLoading(false);
    }
  };

  const changeLaunchMode = (mode: "switch" | "multi") => {
    if (mode === "multi") {
      Modal.confirm({
        title: "切换到多开隔离模式",
        content: appState.runningCount > 0
          ? "检测到 Codex 正在运行。建议先关闭当前 Codex；多开隔离模式会为每个账号复制一整份 CodexPortableApp，磁盘占用约等于 Codex 程序大小 × 多开账号数。"
          : "多开隔离模式会为每个账号复制一整份 CodexPortableApp，磁盘占用约等于 Codex 程序大小 × 多开账号数。",
        okText: "切换",
        cancelText: "取消",
        onOk: () => saveLaunchMode(mode),
      });
      return;
    }
    void saveLaunchMode(mode);
  };

  return (
    <div className="mx-auto max-w-[800px] pb-8 pt-2">
      <Form form={form} layout="vertical">
        <div className="mb-5 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-brand-50 text-brand-600">
            <HardDrive size={16} />
          </div>
          <h2 className="m-0 text-lg font-bold leading-none text-slate-800">
            账号资料
          </h2>
        </div>

        <div className="rounded-xl border border-[#e4ebf3] bg-slate-50/50 p-6">
          <Form.Item
            label={
              <span className="font-semibold text-slate-700">
                账号资料根目录
              </span>
            }
            className="mb-0"
            extra=""
          >
            <Space.Compact className="w-full">
              <Form.Item name="profileRoot" noStyle>
                <Input
                  className="flex-1 bg-white"
                  placeholder="D:\CodexProfiles"
                />
              </Form.Item>
              <Button
                onClick={() =>
                  runCommand(
                    "set_profile_root",
                    { profileRoot: form.getFieldValue("profileRoot") },
                    "已保存账号资料根目录",
                  )
                }
              >
                使用当前路径
              </Button>
              <Button
                type="primary"
                icon={<FolderOpen size={14} />}
                onClick={chooseProfileRoot}
              >
                更改位置
              </Button>
            </Space.Compact>
          </Form.Item>
        </div>

        <div className="mb-5 mt-8 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-brand-50 text-brand-600">
            <Power size={16} />
          </div>
          <h2 className="m-0 text-lg font-bold leading-none text-slate-800">
            启动设置
          </h2>
        </div>

        <div className="rounded-xl border border-[#e4ebf3] bg-slate-50/50 p-6">
          <div className="mb-6 border-b border-slate-200 pb-5">
            <div className="mb-3 font-semibold text-slate-700">启动模式</div>
            <Radio.Group
              value={appState.launchMode}
              disabled={launchModeLoading}
              onChange={(event) => changeLaunchMode(event.target.value)}
            >
              <Radio.Button value="switch">账号切换模式</Radio.Button>
              <Radio.Button value="multi">多开隔离模式</Radio.Button>
            </Radio.Group>
            <div className="mt-3 text-sm leading-6 text-slate-500">
              账号切换模式共用系统 .codex；多开隔离模式为每个账号使用独立环境，可同时运行多个 Codex。
            </div>
            {appState.launchMode === "multi" ? (
              <Alert
                className="mt-3"
                type="warning"
                showIcon
                message="多开模式会复制完整 CodexPortableApp"
                description="如果账号较多，磁盘占用会随账号数量增长。运行中的多开实例需要先关闭，才能切回账号切换模式。"
              />
            ) : null}
          </div>
          <div className="flex items-center justify-between gap-6">
            <div className="min-w-0">
              <div className="font-semibold text-slate-700">开机自启</div>
              <div className="mt-1 text-sm leading-6 text-slate-500">
                登录 Windows 后自动启动 Codex Forge。
              </div>
            </div>
            <Switch
              checked={autoStartEnabled}
              loading={autoStartLoading}
              onChange={changeAutoStartEnabled}
            />
          </div>
        </div>

        <div className="mb-5 mt-8 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-brand-50 text-brand-600">
            <Info size={16} />
          </div>
          <h2 className="m-0 text-lg font-bold leading-none text-slate-800">
            关于
          </h2>
        </div>

        <div className="rounded-xl border border-[#e4ebf3] bg-slate-50/50 p-6">
          <div className="flex items-center justify-between gap-6">
            <div className="min-w-0">
              <div className="font-semibold text-slate-700">Codex Forge</div>
              <div className="mt-1 text-sm leading-6 text-slate-500">
                当前版本
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="shrink-0 rounded bg-white px-3 py-1.5 text-sm font-bold text-brand-700 shadow-sm ring-1 ring-slate-900/5">
                {appVersion ? `v${appVersion}` : "-"}
              </div>
              <Button
                icon={<RefreshCw size={16} />}
                loading={checkUpdateLoading}
                onClick={checkForUpdates}
              >
                检查更新
              </Button>
              <Button
                aria-label="打开 GitHub 项目"
                icon={<Github size={16} />}
                onClick={() => {
                  void window.launcherApi.openProjectGitHub?.();
                }}
              />
              <Button
                aria-label="打开 Gitee 项目"
                icon={<GiteeIcon size={16} />}
                onClick={() => {
                  void window.launcherApi.openProjectGitee?.();
                }}
              />
            </div>
          </div>
        </div>
      </Form>
    </div>
  );
}
