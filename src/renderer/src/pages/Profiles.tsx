import { useEffect, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tooltip,
  Typography,
} from "antd";
import {
  FolderOpen,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
  UserPen,
} from "lucide-react";
import type { ProfileSummary, ProfileUsageWindow, RunCommand } from "../types";

type ProfilesProps = {
  profiles: ProfileSummary[];
  runCommand: RunCommand;
  loading: boolean;
};

const profileRowBaseClass =
  "flex items-center gap-4 border-b border-[#ecf1f6] px-5 py-4 transition-colors last:border-b-0 hover:bg-slate-50 max-[960px]:items-start";

const profilePillBaseClass =
  "inline-flex h-[22px] items-center rounded-[6px] px-2 text-[11.5px] font-bold leading-none border";

const iconActionButtonClass =
  "flex items-center justify-center text-slate-500 hover:!text-brand-600";

export function Profiles({ profiles, runCommand, loading }: ProfilesProps) {
  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<ProfileSummary | null>(null);
  const [pendingProfileNames, setPendingProfileNames] = useState<Set<string>>(
    () => new Set(),
  );
  const [pendingUsageProfileNames, setPendingUsageProfileNames] = useState<
    Set<string>
  >(() => new Set());
  const [refreshingAllUsage, setRefreshingAllUsage] = useState(false);
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
      onOk: () =>
        runCommand("delete_profile", { name: profile.name }, "已删除账号"),
    });
  };

  const toggleProfileRunning = async (profile: ProfileSummary) => {
    setPendingProfileNames((current) => new Set(current).add(profile.name));
    try {
      await runCommand(
        profile.running ? "stop_profile" : "launch_profile",
        { name: profile.name },
        profile.running ? "已停止账号" : "已启动账号",
        { blocking: false },
      );
    } finally {
      setPendingProfileNames((current) => {
        const next = new Set(current);
        next.delete(profile.name);
        return next;
      });
    }
  };

  const refreshAllUsage = async () => {
    setRefreshingAllUsage(true);
    try {
      await runCommand(
        "refresh_all_profile_usage",
        {},
        "额度已刷新",
        { blocking: false },
      );
    } finally {
      setRefreshingAllUsage(false);
    }
  };

  const refreshProfileUsage = async (profile: ProfileSummary) => {
    setPendingUsageProfileNames((current) => new Set(current).add(profile.name));
    try {
      await runCommand(
        "refresh_profile_usage",
        { name: profile.name },
        "额度已刷新",
        { blocking: false },
      );
    } finally {
      setPendingUsageProfileNames((current) => {
        const next = new Set(current);
        next.delete(profile.name);
        return next;
      });
    }
  };

  return (
    <div className="overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
      <div className="flex items-center justify-between gap-4 border-b border-[#ecf1f6] bg-white px-5 py-4 max-[960px]:items-start max-[960px]:flex-col">
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-extrabold leading-none text-gray-900">
            {profiles.length}
          </span>
          <span className="text-sm font-medium text-slate-500">个账号</span>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2.5 max-[960px]:w-full max-[960px]:justify-start">
          <Button
            icon={<RefreshCw size={15} />}
            loading={refreshingAllUsage}
            disabled={pendingUsageProfileNames.size > 0}
            onClick={refreshAllUsage}
          >
            刷新额度
          </Button>
          <Button
            type="primary"
            icon={<Plus size={15} />}
            onClick={() => setCreateOpen(true)}
          >
            新增账号
          </Button>
        </div>
      </div>

      <div className="relative">
        {loading && profiles.length === 0 ? (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
            <Spin />
          </div>
        ) : profiles.length ? (
          profiles.map((profile) => (
            <div
              key={profile.name}
              className={
                profile.running
                  ? `${profileRowBaseClass} bg-green-50/40 hover:bg-green-50/60`
                  : profileRowBaseClass
              }
            >
              <div
                className={
                  profile.running
                    ? "self-stretch rounded-full bg-green-500 basis-[3px] shrink-0"
                    : "self-stretch rounded-full bg-[#ecf1f6] basis-[3px] shrink-0"
                }
                aria-hidden
              />
              <div className="min-w-0 flex-auto">
                <div className="mb-1.5 flex flex-wrap items-center gap-2.5">
                  <span className="text-[15px] font-bold leading-snug text-gray-900">
                    {profile.name}
                  </span>
                  <span
                    className={
                      profile.running
                        ? `${profilePillBaseClass} border-green-200 bg-green-50 text-green-600`
                        : `${profilePillBaseClass} border-slate-200 bg-slate-50 text-slate-500`
                    }
                  >
                    {profile.running ? "运行中" : "就绪"}
                  </span>
                  <span
                    className={
                      profile.portableCodexExists
                        ? `${profilePillBaseClass} border-emerald-200 bg-emerald-50 text-emerald-600`
                        : `${profilePillBaseClass} border-amber-200 bg-amber-50 text-amber-600`
                    }
                  >
                    {profile.portableCodexExists ? "副本已准备" : "副本未准备"}
                  </span>
                </div>
                <Tooltip title={profile.profileDir} placement="topLeft">
                  <div className="truncate font-mono text-xs leading-normal text-slate-400">
                    {profile.profileDir}
                  </div>
                </Tooltip>
                <div className="mt-3 grid max-w-[520px] grid-cols-[max-content_minmax(108px,0.22fr)_minmax(108px,0.22fr)] items-center gap-3 max-[960px]:max-w-none max-[960px]:grid-cols-1">
                  <span className="inline-flex h-6 w-fit items-center justify-center justify-self-start whitespace-nowrap rounded-[6px] border border-blue-200 bg-blue-50 px-2 text-[11.5px] font-bold text-blue-600">
                    {formatPlanType(profile.usage?.planType)}
                  </span>
                  {profile.usage?.error ? (
                    <Tooltip title={profile.usage.error}>
                      <span className="col-span-2 min-w-0 truncate text-[11.5px] text-red-500 max-[960px]:col-auto">
                        {profile.usage.error}
                      </span>
                    </Tooltip>
                  ) : (
                    <>
                      <UsageMeter
                        label="五小时"
                        window={profile.usage?.fiveHour ?? null}
                      />
                      <UsageMeter
                        label="一周"
                        window={profile.usage?.oneWeek ?? null}
                      />
                    </>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 items-center max-[960px]:items-end max-[960px]:flex-col">
                <Space.Compact>
                  {(() => {
                    const isPending = pendingProfileNames.has(profile.name);

                    return (
                      <Button
                        type="primary"
                        danger={profile.running}
                        icon={
                          profile.running ? (
                            <Square size={14} />
                          ) : (
                            <Play size={14} />
                          )
                        }
                        loading={isPending}
                        disabled={isPending}
                        onClick={() => toggleProfileRunning(profile)}
                      >
                        {isPending
                          ? profile.running
                            ? "停止中"
                            : "启动中"
                          : profile.running
                            ? "停止"
                            : "启动"}
                      </Button>
                    );
                  })()}
                  <Tooltip title="刷新额度">
                    <Button
                      className={iconActionButtonClass}
                      icon={<RefreshCw size={14} />}
                      loading={pendingUsageProfileNames.has(profile.name)}
                      disabled={refreshingAllUsage}
                      onClick={() => refreshProfileUsage(profile)}
                    />
                  </Tooltip>
                  <Tooltip title="改名">
                    <Button
                      className={iconActionButtonClass}
                      icon={<UserPen size={14} />}
                      onClick={() => setRenameTarget(profile)}
                    />
                  </Tooltip>
                  <Tooltip title="打开目录">
                    <Button
                      className={iconActionButtonClass}
                      icon={<FolderOpen size={14} />}
                      onClick={() =>
                        runCommand(
                          "open_path",
                          { path: profile.profileDir },
                          "已打开目录",
                          { blocking: false, refreshAfter: false },
                        )
                      }
                    />
                  </Tooltip>
                  <Tooltip title="删除">
                    <Button
                      className={`${iconActionButtonClass} !text-red-500 hover:!bg-red-50 hover:!text-red-600 hover:!border-red-200`}
                      icon={<Trash2 size={14} />}
                      onClick={() => confirmDelete(profile)}
                    />
                  </Tooltip>
                </Space.Compact>
              </div>
            </div>
          ))
        ) : (
          <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
            <Empty description="暂无账号">
              <Button
                type="primary"
                icon={<Plus size={16} />}
                onClick={() => setCreateOpen(true)}
              >
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
          <Form.Item
            name="name"
            label="账号名称"
            rules={[{ required: true, message: "请输入账号名称" }]}
          >
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
          await runCommand(
            "rename_profile",
            { oldName, newName: values.name },
            "已修改账号名称",
          );
          renameForm.resetFields();
        }}
      >
        <Form form={renameForm} layout="vertical">
          <Form.Item
            name="name"
            label="新名称"
            rules={[{ required: true, message: "请输入新名称" }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function UsageMeter({
  label,
  window,
}: {
  label: string;
  window: ProfileUsageWindow | null;
}) {
  const usedText = formatPercent(window?.usedPercent);
  const remainingText = formatPercent(window?.remainingPercent);
  const resetText = formatResetAt(window?.resetAt);

  const percent = clampPercent(window?.usedPercent);
  let barColor = "bg-green-500";
  if (percent > 80) barColor = "bg-red-500";
  else if (percent > 50) barColor = "bg-amber-500";

  return (
    <Tooltip
      title={`已用 ${usedText}，剩余 ${remainingText}，重置时间 ${resetText}`}
    >
      <span className="grid min-w-0 gap-1.5">
        <span className="flex items-center justify-between gap-2 text-[11.5px] leading-none text-slate-500">
          <span>{label}</span>
          <strong className="text-[11.5px] text-gray-900">
            {remainingText}
          </strong>
        </span>
        <span
          className="block h-[5px] overflow-hidden rounded-full bg-slate-100"
          aria-hidden
        >
          <span
            className={`block h-full rounded-full transition-all duration-300 ${barColor}`}
            style={{ width: `${percent}%` }}
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
