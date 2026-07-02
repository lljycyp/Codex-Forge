import { useEffect } from "react";
import { Button, Form, Input, Modal, Space } from "antd";
import { FolderOpen, HardDrive } from "lucide-react";
import type { AppState, RunCommand } from "../types";

type SettingsPageProps = {
  appState: AppState;
  runCommand: RunCommand;
};

export function SettingsPage({ appState, runCommand }: SettingsPageProps) {
  const [form] = Form.useForm();

  useEffect(() => {
    form.setFieldsValue({
      profileRoot: appState.profileRoot,
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
      </Form>
    </div>
  );
}
