import { useEffect } from "react";
import { Button, Card, Form, Input, Modal, Space, Switch } from "antd";
import { FolderOpen, RefreshCw } from "lucide-react";
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
      memorySyncEnabled: appState.memorySyncEnabled
    });
  }, [appState, form]);

  const chooseProfileRoot = async () => {
    const selectedPath = await window.launcherApi.selectDirectory(appState.profileRoot || undefined);
    if (!selectedPath) {
      return;
    }
    Modal.confirm({
      title: "更改账号存放位置",
      content: "将迁移整个 CodexProfiles 账号根目录。迁移期间请先关闭正在运行的 Codex 账号窗口。",
      okText: "开始迁移",
      cancelText: "取消",
      onOk: async () => {
        form.setFieldsValue({ profileRoot: selectedPath });
        await runCommand(
          "set_profile_root",
          { profileRoot: selectedPath, asStorageLocation: true },
          "账号存放位置已更新"
        );
      }
    });
  };

  return (
    <Card title="设置" className="shadow-none">
      <Form form={form} layout="vertical" className="max-w-[760px]">
        <Form.Item label="Codex 程序路径" name="codexPath">
          <Input />
        </Form.Item>
        <Space>
          <Button
            onClick={() =>
              runCommand("set_codex_path", { codexPath: form.getFieldValue("codexPath") }, "已保存程序路径")
            }
          >
            保存路径
          </Button>
          <Button icon={<RefreshCw size={16} />} onClick={() => runCommand("refresh_codex_source", {}, "已重新识别")}>
            重新识别
          </Button>
        </Space>
        <Form.Item label="账号根目录" name="profileRoot" className="mt-[22px]">
          <Input />
        </Form.Item>
        <Space>
          <Button type="primary" icon={<FolderOpen size={16} />} onClick={chooseProfileRoot}>
            更改存放位置
          </Button>
          <Button
            onClick={() =>
              runCommand("set_profile_root", { profileRoot: form.getFieldValue("profileRoot") }, "已保存账号根目录")
            }
          >
            使用当前路径
          </Button>
        </Space>
        <div className="mt-[18px] flex h-[42px] max-w-[420px] items-center justify-between">
          <span>实验性会话同步</span>
          <Switch
            checked={appState.sessionSyncEnabled}
            onChange={(enabled) => runCommand("set_session_sync", { enabled }, "已保存会话同步设置")}
          />
        </div>
        <div className="mt-[18px] flex h-[42px] max-w-[420px] items-center justify-between">
          <span>实验性记忆同步</span>
          <Switch
            checked={appState.memorySyncEnabled}
            onChange={(enabled) => runCommand("set_memory_sync", { enabled }, "已保存记忆同步设置")}
          />
        </div>
      </Form>
    </Card>
  );
}
