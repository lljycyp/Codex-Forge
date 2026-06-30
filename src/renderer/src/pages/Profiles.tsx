import { useEffect, useState } from "react";
import { Button, Empty, Form, Input, Modal, Spin, Tooltip, Typography } from "antd";
import { FolderOpen, Play, Plus, Trash2, UserPen } from "lucide-react";
import type { ProfileSummary, RunCommand } from "../types";

type ProfilesProps = {
  profiles: ProfileSummary[];
  runCommand: RunCommand;
  loading: boolean;
};

export function Profiles({ profiles, runCommand, loading }: ProfilesProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ProfileSummary | null>(null);
  const [createForm] = Form.useForm();
  const [renameForm] = Form.useForm();

  useEffect(() => {
    if (renameTarget) {
      renameForm.setFieldsValue({ name: renameTarget.name });
    }
  }, [renameForm, renameTarget]);

  const confirmDelete = (profile: ProfileSummary) => {
    Modal.confirm({
      title: "删除账号",
      content: `确认删除「${profile.name}」？该账号目录也会被删除。`,
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => runCommand("delete_profile", { name: profile.name }, "已删除账号")
    });
  };

  return (
    <div className="profiles-page">
      <div className="profiles-toolbar">
        <div className="profiles-summary">
          <span className="profiles-count">{profiles.length}</span>
          <Typography.Text type="secondary">个账号</Typography.Text>
        </div>
        <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>
          新增账号
        </Button>
      </div>

      <div className={`profiles-list${loading ? " is-loading" : ""}`}>
        {loading && profiles.length === 0 ? (
          <div className="profiles-state">
            <Spin />
          </div>
        ) : profiles.length ? (
          profiles.map((profile) => (
            <div key={profile.name} className={`profile-row${profile.running ? " is-running" : ""}`}>
              <div className="profile-row-accent" aria-hidden />
              <div className="profile-row-body">
                <div className="profile-row-head">
                  <span className="profile-row-name">{profile.name}</span>
                  <span className={`profile-pill${profile.running ? " is-active" : ""}`}>
                    {profile.running ? "运行中" : "就绪"}
                  </span>
                  <span className={`profile-pill is-copy${profile.portableCodexExists ? " is-ready" : " is-pending"}`}>
                    {profile.portableCodexExists ? "副本已准备" : "副本未准备"}
                  </span>
                </div>
                <Tooltip title={profile.profileDir} placement="topLeft">
                  <div className="profile-row-path">{profile.profileDir}</div>
                </Tooltip>
              </div>
              <div className="profile-row-actions">
                <Button
                  type="primary"
                  icon={<Play size={15} />}
                  onClick={() => runCommand("launch_profile", { name: profile.name }, "已启动账号")}
                >
                  启动
                </Button>
                <div className="profile-icon-actions">
                  <Tooltip title="改名">
                    <Button type="text" icon={<UserPen size={16} />} onClick={() => setRenameTarget(profile)} />
                  </Tooltip>
                  <Tooltip title="打开目录">
                    <Button
                      type="text"
                      icon={<FolderOpen size={16} />}
                      onClick={() => runCommand("open_path", { path: profile.profileDir }, "已打开目录")}
                    />
                  </Tooltip>
                  <Tooltip title="删除">
                    <Button type="text" danger icon={<Trash2 size={16} />} onClick={() => confirmDelete(profile)} />
                  </Tooltip>
                </div>
              </div>
            </div>
          ))
        ) : (
          <div className="profiles-state">
            <Empty description="暂无账号">
              <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>
                新增第一个账号
              </Button>
            </Empty>
          </div>
        )}
      </div>

      <Modal
        title="新增账号"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={async () => {
          const values = await createForm.validateFields();
          setCreateOpen(false);
          await runCommand("create_profile", values, "已新增账号");
          createForm.resetFields();
        }}
      >
        <Form form={createForm} layout="vertical">
          <Form.Item name="name" label="账号名称" rules={[{ required: true, message: "请输入账号名称" }]}>
            <Input placeholder="例如：工作号" />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title="修改账号名称"
        open={Boolean(renameTarget)}
        onCancel={() => setRenameTarget(null)}
        onOk={async () => {
          const values = await renameForm.validateFields();
          const oldName = renameTarget?.name;
          setRenameTarget(null);
          await runCommand("rename_profile", { oldName, newName: values.name }, "已修改账号名称");
          renameForm.resetFields();
        }}
      >
        <Form form={renameForm} layout="vertical">
          <Form.Item name="name" label="新名称" rules={[{ required: true, message: "请输入新名称" }]}>
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
