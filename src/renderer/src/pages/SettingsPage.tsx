import { useEffect } from "react";
import { Button, Form, Input, Modal, Space, Switch, Divider } from "antd";
import { FolderOpen, RefreshCw, Cpu, Cloud } from "lucide-react";
import type { AppState, RunCommand } from "../types";

type SettingsPageProps = {
  appState: AppState;
  runCommand: RunCommand;
};

export function SettingsPage({ appState, runCommand }: SettingsPageProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      codexPath: appState.codexPath,
      profileRoot: appState.profileRoot,
      sessionSyncEnabled: appState.sessionSyncEnabled,
      sessionSyncRoot: appState.sessionSyncRoot,
      memorySyncEnabled: appState.memorySyncEnabled,
      memorySyncDatabase: appState.memorySyncDatabase,
    });
  }, [appState, form]);

  const chooseProfileRoot = async () => {
    const selectedPath = await window.launcherApi.selectDirectory(
      appState.profileRoot || undefined,
    );
    if (!selectedPath) {
      return;
    }
    Modal.confirm({
      title: "更改账号存放位置",
      content:
        "将迁移整个 CodexProfiles 账号根目录。迁移期间请先关闭正在运行的 Codex 账号窗口。",
      okText: "开始迁移",
      cancelText: "取消",
      onOk: async () => {
        form.setFieldsValue({ profileRoot: selectedPath });
        await runCommand(
          "set_profile_root",
          { profileRoot: selectedPath, asStorageLocation: true },
          "账号存放位置已更新",
        );
      },
    });
  };

  return (
    <div className="mx-auto max-w-[800px] pb-8 pt-2">
      <Form form={form} layout="vertical">
        {/* 核心配置区块 */}
        <div className="mb-5 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-brand-50 text-brand-600">
            <Cpu size={16} />
          </div>
          <h2 className="m-0 text-lg font-bold leading-none text-slate-800">
            核心配置
          </h2>
        </div>

        <div className="rounded-xl border border-[#e4ebf3] bg-slate-50/50 p-6">
          <Form.Item
            label={
              <span className="font-semibold text-slate-700">
                Codex 程序路径
              </span>
            }
            className="mb-6"
            extra="指定 Codex.exe 的绝对路径，用于启动客户端"
          >
            <Space.Compact className="w-full">
              <Form.Item name="codexPath" noStyle>
                <Input
                  className="flex-1 bg-white"
                  placeholder="C:\Program Files\...\Codex.exe"
                />
              </Form.Item>
              <Button
                onClick={() =>
                  runCommand(
                    "set_codex_path",
                    { codexPath: form.getFieldValue("codexPath") },
                    "已保存程序路径",
                  )
                }
              >
                保存路径
              </Button>
              <Button
                icon={<RefreshCw size={14} />}
                onClick={() =>
                  runCommand("refresh_codex_source", {}, "已重新识别")
                }
              >
                重新识别
              </Button>
            </Space.Compact>
          </Form.Item>

          <Form.Item
            label={
              <span className="font-semibold text-slate-700">账号根目录</span>
            }
            className="mb-0"
            extra="所有独立环境和数据的存储根目录 (通常为 CodexProfiles)"
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
                    "已保存账号根目录",
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
                更改存放位置
              </Button>
            </Space.Compact>
          </Form.Item>
        </div>

        <Divider className="my-10 border-[#e4ebf3]" />

        {/* 数据同步区块 */}
        <div className="mb-5 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded bg-emerald-50 text-emerald-600">
            <Cloud size={16} />
          </div>
          <h2 className="m-0 text-lg font-bold leading-none text-slate-800">
            数据同步
          </h2>
        </div>

        <div className="flex flex-col gap-5">
          {/* 会话同步卡片 */}
          <div className="rounded-xl border border-[#e4ebf3] bg-white p-5 shadow-sm transition-colors hover:border-emerald-200">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[15px] font-bold text-slate-800">
                  实验性会话同步
                </div>
                <div className="mt-1 text-sm text-slate-500">
                  开启后，将在配置的共享目录下同步所有账号的本地会话状态
                </div>
              </div>
              <Switch
                checked={appState.sessionSyncEnabled}
                onChange={(enabled) =>
                  runCommand(
                    "set_session_sync",
                    { enabled },
                    "已保存会话同步设置",
                  )
                }
              />
            </div>
            {appState.sessionSyncEnabled && (
              <div className="mt-5 border-t border-[#e4ebf3] pt-5">
                <Form.Item
                  label={<span className="text-slate-600">共享会话路径</span>}
                  className="mb-0"
                >
                  <Space.Compact className="w-full">
                    <Form.Item name="sessionSyncRoot" noStyle>
                      <Input
                        readOnly
                        className="flex-1 bg-slate-50 text-slate-500 hover:bg-slate-50 focus:bg-slate-50"
                      />
                    </Form.Item>
                    <Button
                      icon={<FolderOpen size={14} />}
                      onClick={() =>
                        runCommand(
                          "open_session_sync_dir",
                          {},
                          "已打开共享会话目录",
                          { blocking: false, refreshAfter: false },
                        )
                      }
                    >
                      打开目录
                    </Button>
                  </Space.Compact>
                </Form.Item>
              </div>
            )}
          </div>

          {/* 记忆同步卡片 */}
          <div className="rounded-xl border border-[#e4ebf3] bg-white p-5 shadow-sm transition-colors hover:border-emerald-200">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[15px] font-bold text-slate-800">
                  实验性记忆同步
                </div>
                <div className="mt-1 text-sm text-slate-500">
                  开启后，使用集中的 SQLite 数据库来同步全局记忆和上下文
                </div>
              </div>
              <Switch
                checked={appState.memorySyncEnabled}
                onChange={(enabled) =>
                  runCommand(
                    "set_memory_sync",
                    { enabled },
                    "已保存记忆同步设置",
                  )
                }
              />
            </div>
            {appState.memorySyncEnabled && (
              <div className="mt-5 border-t border-[#e4ebf3] pt-5">
                <Form.Item
                  label={<span className="text-slate-600">共享记忆数据库</span>}
                  className="mb-0"
                >
                  <Space.Compact className="w-full">
                    <Form.Item name="memorySyncDatabase" noStyle>
                      <Input
                        readOnly
                        className="flex-1 bg-slate-50 text-slate-500 hover:bg-slate-50 focus:bg-slate-50"
                      />
                    </Form.Item>
                    <Button
                      icon={<FolderOpen size={14} />}
                      onClick={() =>
                        runCommand(
                          "open_session_sync_dir",
                          {},
                          "已打开同步共享目录",
                          { blocking: false, refreshAfter: false },
                        )
                      }
                    >
                      打开目录
                    </Button>
                  </Space.Compact>
                </Form.Item>
              </div>
            )}
          </div>
        </div>
      </Form>
    </div>
  );
}
