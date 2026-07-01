import { useEffect, useState } from "react";
import { Button, Empty, Form, Input, Modal, Spin, Tooltip, Typography } from "antd";
import { FolderOpen, Play, Plus, RefreshCw, Square, Trash2, UserPen } from "lucide-react";
import type { ProfileSummary, ProfileUsageWindow, RunCommand } from "../types";

type ProfilesProps = {
  profiles: ProfileSummary[];
  runCommand: RunCommand;
  loading: boolean;
};

const profileRowBaseClass =
  "flex items-center gap-4 border-b border-[#ecf1f6] px-[22px] py-4 transition-colors last:border-b-0 hover:bg-slate-50 max-[960px]:items-start";

const profilePillBaseClass =
  "inline-flex h-[22px] items-center rounded-full px-2 text-xs font-semibold leading-none";

const iconActionButtonClass =
  "h-[34px] w-[34px] p-0 text-slate-500 hover:!bg-brand-50 hover:!text-brand-600";

export function Profiles({ profiles, runCommand, loading }: ProfilesProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ProfileSummary | null>(null);
  const [pendingProfileName, setPendingProfileName] = useState<string | null>(null);
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

  const toggleProfileRunning = async (profile: ProfileSummary) => {
    setPendingProfileName(profile.name);
    try {
      await runCommand(
        profile.running ? "stop_profile" : "launch_profile",
        { name: profile.name },
        profile.running ? "已停止账号" : "已启动账号"
      );
    } finally {
      setPendingProfileName(null);
    }
  };

  return (
    <div className="overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
      <div className="flex items-center justify-between gap-4 border-b border-[#ecf1f6] bg-white px-[22px] py-[18px] max-[960px]:items-start max-[960px]:flex-col">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[28px] font-extrabold leading-none text-gray-900">{profiles.length}</span>
          <Typography.Text type="secondary">个账号</Typography.Text>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2.5 max-[960px]:w-full max-[960px]:justify-start">
          <Button icon={<RefreshCw size={16} />} onClick={() => runCommand("refresh_all_profile_usage", {}, "额度已刷新")}>
            刷新额度
          </Button>
          <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>
            新增账号
          </Button>
        </div>
      </div>

      <div className={loading ? "relative pointer-events-none opacity-70" : "relative"}>
        {loading && profiles.length === 0 ? (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
            <Spin />
          </div>
        ) : profiles.length ? (
          profiles.map((profile) => (
            <div key={profile.name} className={profile.running ? `${profileRowBaseClass} bg-green-50` : profileRowBaseClass}>
              <div
                className={profile.running ? "self-stretch rounded-full bg-green-600 basis-[3px] shrink-0" : "self-stretch rounded-full bg-shell-line basis-[3px] shrink-0"}
                aria-hidden
              />
              <div className="min-w-0 flex-auto">
                <div className="mb-1.5 flex flex-wrap items-center gap-2">
                  <span className="text-[15px] font-bold leading-snug text-gray-900">{profile.name}</span>
                  <span
                    className={
                      profile.running
                        ? `${profilePillBaseClass} bg-green-100 text-green-700`
                        : `${profilePillBaseClass} bg-slate-100 text-slate-500`
                    }
                  >
                    {profile.running ? "运行中" : "就绪"}
                  </span>
                  <span
                    className={
                      profile.portableCodexExists
                        ? `${profilePillBaseClass} bg-green-100 text-green-700`
                        : `${profilePillBaseClass} bg-amber-100 text-amber-700`
                    }
                  >
                    {profile.portableCodexExists ? "副本已准备" : "副本未准备"}
                  </span>
                </div>
                <Tooltip title={profile.profileDir} placement="topLeft">
                  <div className="truncate font-mono text-[12.5px] leading-normal text-shell-muted">{profile.profileDir}</div>
                </Tooltip>
                <div className="mt-2.5 grid max-w-[520px] grid-cols-[minmax(70px,auto)_minmax(108px,0.22fr)_minmax(108px,0.22fr)] items-center gap-2 max-[960px]:max-w-none max-[960px]:grid-cols-1">
                  <span className="inline-flex h-6 min-w-[66px] items-center justify-center whitespace-nowrap rounded-[7px] bg-blue-50 px-2 text-xs font-bold text-blue-700 max-[960px]:justify-self-start">
                    {formatPlanType(profile.usage?.planType)}
                  </span>
                  {profile.usage?.error ? (
                    <Tooltip title={profile.usage.error}>
                      <span className="col-span-2 min-w-0 truncate text-xs text-[#b42318] max-[960px]:col-auto">
                        {profile.usage.error}
                      </span>
                    </Tooltip>
                  ) : (
                    <>
                      <UsageMeter label="五小时" window={profile.usage?.fiveHour ?? null} />
                      <UsageMeter label="一周" window={profile.usage?.oneWeek ?? null} />
                    </>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-1 max-[960px]:items-end max-[960px]:flex-col">
                {(() => {
                  const isPending = pendingProfileName === profile.name;
                  const isDisabled = loading && !isPending;

                  return (
                    <Button
                      type="primary"
                      danger={profile.running}
                      icon={profile.running ? <Square size={15} /> : <Play size={15} />}
                      loading={isPending}
                      disabled={isDisabled}
                      onClick={() => toggleProfileRunning(profile)}
                    >
                      {isPending ? (profile.running ? "停止中" : "启动中") : profile.running ? "停止" : "启动"}
                    </Button>
                  );
                })()}
                <div className="ml-0.5 flex items-center border-l border-[#ecf1f6] pl-1.5 max-[960px]:ml-0 max-[960px]:border-l-0 max-[960px]:pl-0">
                  <Tooltip title="刷新额度">
                    <Button
                      type="text"
                      className={iconActionButtonClass}
                      icon={<RefreshCw size={16} />}
                      onClick={() => runCommand("refresh_profile_usage", { name: profile.name }, "额度已刷新")}
                    />
                  </Tooltip>
                  <Tooltip title="改名">
                    <Button
                      type="text"
                      className={iconActionButtonClass}
                      icon={<UserPen size={16} />}
                      onClick={() => setRenameTarget(profile)}
                    />
                  </Tooltip>
                  <Tooltip title="打开目录">
                    <Button
                      type="text"
                      className={iconActionButtonClass}
                      icon={<FolderOpen size={16} />}
                      onClick={() => runCommand("open_path", { path: profile.profileDir }, "已打开目录")}
                    />
                  </Tooltip>
                  <Tooltip title="删除">
                    <Button
                      type="text"
                      danger
                      className={`${iconActionButtonClass} hover:!bg-red-50 hover:!text-red-600`}
                      icon={<Trash2 size={16} />}
                      onClick={() => confirmDelete(profile)}
                    />
                  </Tooltip>
                </div>
              </div>
            </div>
          ))
        ) : (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
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

function UsageMeter({ label, window }: { label: string; window: ProfileUsageWindow | null }) {
  const usedText = formatPercent(window?.usedPercent);
  const remainingText = formatPercent(window?.remainingPercent);
  const resetText = formatResetAt(window?.resetAt);

  return (
    <Tooltip title={`已用 ${usedText}，剩余 ${remainingText}，重置时间 ${resetText}`}>
      <span className="grid min-w-0 gap-[5px]">
        <span className="flex items-center justify-between gap-2 text-[11.5px] leading-none text-shell-muted">
          <span>{label}</span>
          <strong className="text-xs text-gray-900">{remainingText}</strong>
        </span>
        <span className="block h-1.5 overflow-hidden rounded-full bg-gray-200" aria-hidden>
          <span
            className="block h-full rounded-[inherit] bg-[linear-gradient(90deg,#16a34a,#f59e0b)]"
            style={{ width: `${clampPercent(window?.usedPercent)}%` }}
          />
        </span>
      </span>
    </Tooltip>
  );
}

function formatPlanType(planType: string | null | undefined) {
  const normalized = planType?.trim().toLowerCase();
  if (normalized === "free") return "免费版";
  if (normalized === "plus") return "增强版";
  if (normalized === "pro") return "专业版";
  if (normalized === "team") return "团队版";
  if (normalized === "enterprise") return "企业版";
  if (normalized === "business") return "商业版";
  return "套餐未识别";
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return `${clampPercent(value).toFixed(0)}%`;
}

function clampPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function formatResetAt(value: number | null | undefined) {
  if (!value) {
    return "未返回";
  }
  return new Date(value * 1000).toLocaleString("zh-CN");
}
