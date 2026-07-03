import { useEffect, useState } from "react";
import { Button, Form, Input, message, Modal, Space, Switch } from "antd";
import { FolderOpen, HardDrive, Power } from "lucide-react";
import type { AppState, RunCommand } from "../types";

type SettingsPageProps = {
  appState: AppState;
  runCommand: RunCommand;
};

export function SettingsPage({ appState, runCommand }: SettingsPageProps) {
  const [form] = Form.useForm();
  const [autoStartEnabled, setAutoStartEnabled] = useState(false);
  const [autoStartLoading, setAutoStartLoading] = useState(false);
  const [shareConfigLoading, setShareConfigLoading] = useState(false);

  useEffect(() => {
    form.setFieldsValue({
      profileRoot: appState.profileRoot,
    });
  }, [appState, form]);

  useEffect(() => {
    let disposed = false;
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

  const changeShareSystemConfig = async (enabled: boolean) => {
    setShareConfigLoading(true);
    try {
      await runCommand(
        "set_share_system_config",
        { enabled },
        enabled ? "已开启共享系统配置" : "已关闭共享系统配置",
        { blocking: false },
      );
    } finally {
      setShareConfigLoading(false);
    }
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
          <div className="mt-6 flex items-center justify-between gap-6 border-t border-slate-200 pt-5">
            <div className="min-w-0">
              <div className="font-semibold text-slate-700">多账号共享系统配置</div>
              <div className="mt-1 text-sm leading-6 text-slate-500">
                开启后切换账号只更换登录信息，模型、代理和其他 Codex 配置始终使用系统当前 config.toml。
              </div>
            </div>
            <Switch
              checked={appState.shareSystemConfig}
              loading={shareConfigLoading}
              onChange={changeShareSystemConfig}
            />
          </div>
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
          <div className="flex items-center justify-between gap-6">
            <div className="min-w-0">
              <div className="font-semibold text-slate-700">开机自启</div>
              <div className="mt-1 text-sm leading-6 text-slate-500">
                登录 Windows 后自动启动 Codex 多账号切换器。
              </div>
            </div>
            <Switch
              checked={autoStartEnabled}
              loading={autoStartLoading}
              onChange={changeAutoStartEnabled}
            />
          </div>
        </div>
      </Form>
    </div>
  );
}
