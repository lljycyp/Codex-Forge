import { useEffect, useState, type ReactNode } from "react";
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Radio,
  Space,
  Spin,
  Tabs,
  Tooltip,
  Typography,
} from "antd";
import {
  Archive,
  Download,
  FolderOpen,
  Info,
  KeyRound,
  Play,
  Plus,
  RefreshCw,
  ShieldAlert,
  Square,
  Trash2,
  Upload,
  UserPen,
  WalletCards,
} from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";
import type { ProfileSummary, ProfileUsage, ProfileUsageWindow, RunCommand } from "../types";

type ProfilesProps = {
  profiles: ProfileSummary[];
  runningCount: number;
  launchMode: "switch" | "multi";
  privacyMode: boolean;
  runCommand: RunCommand;
  loading: boolean;
};

type ProfileDetail = ProfileSummary & {
  auth: {
    exists: boolean;
    authMode: "chatgpt" | "api" | "";
    email: string;
    accountId: string;
    planType: string;
    accessTokenExpiresAt: number | null;
    hasRefreshToken: boolean;
    error: string;
  };
};

const profileRowBaseClass =
  "flex items-center gap-4 border-b border-[#ecf1f6] px-5 py-4 transition-colors last:border-b-0 hover:bg-slate-50 max-[960px]:items-start";

const profilePillBaseClass =
  "inline-flex h-[22px] items-center rounded-[6px] px-2 text-[11.5px] font-bold leading-none border";

const iconActionButtonClass =
  "flex items-center justify-center text-slate-500 hover:!text-brand-600";

export function Profiles({ profiles, runningCount, launchMode, privacyMode, runCommand, loading }: ProfilesProps) {
  const { language, t } = useI18n();
  const [createOpen, setCreateOpen] = useState(false);
  const [createMode, setCreateMode] = useState<"oauth" | "current" | "file">("oauth");
  const [authJsonPath, setAuthJsonPath] = useState("");
  const [renameTarget, setRenameTarget] = useState<ProfileSummary | null>(null);
  const [pendingProfileNames, setPendingProfileNames] = useState<Set<string>>(
    () => new Set(),
  );
  const [pendingProfileTexts, setPendingProfileTexts] = useState<
    Map<string, string>
  >(() => new Map());
  const [pendingUsageProfileNames, setPendingUsageProfileNames] = useState<
    Set<string>
  >(() => new Set());
  const [refreshingAllUsage, setRefreshingAllUsage] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [profileDetail, setProfileDetail] = useState<ProfileDetail | null>(null);
  const [restoreOpen, setRestoreOpen] = useState(false);
  const [backupPath, setBackupPath] = useState("");
  const [createForm] = Form.useForm();
  const [renameForm] = Form.useForm();
  const [restoreForm] = Form.useForm();

  useEffect(() => {
    if (renameTarget) {
      renameForm.setFieldsValue({ name: renameTarget.name });
    }
  }, [renameForm, renameTarget]);

  const confirmDelete = (profile: ProfileSummary) => {
    Modal.confirm({
      title: t("删除账号"),
      content: language === "en-US"
        ? `Delete "${profile.name}"? Its profile folder will also be deleted.`
        : `确认删除「${profile.name}」？该账号资料目录也会被删除。`,
      okText: t("删除"),
      okButtonProps: { danger: true },
      cancelText: t("取消"),
      onOk: () =>
        runCommand("delete_profile", { name: profile.name }, t("已删除账号")),
    });
  };

  const executeProfileToggle = async (
    profile: ProfileSummary,
    stopRunningFirst = false,
  ) => {
    const hasRunningCodex = launchMode === "switch" && runningCount > 0;
    const pendingText = profile.running
      ? t("停止中")
      : hasRunningCodex
        ? t("切换中")
        : t("启动中");

    setPendingProfileNames((current) => new Set(current).add(profile.name));
    setPendingProfileTexts((current) => {
      const next = new Map(current);
      next.set(profile.name, pendingText);
      return next;
    });
    try {
      await runCommand(
        profile.running ? "stop_profile" : "launch_profile",
        { name: profile.name, stopRunningFirst },
        profile.running
          ? t("已关闭 ChatGPT")
          : hasRunningCodex
            ? t("已切换")
            : t("已启动"),
        { blocking: false },
      );
    } finally {
      setPendingProfileNames((current) => {
        const next = new Set(current);
        next.delete(profile.name);
        return next;
      });
      setPendingProfileTexts((current) => {
        const next = new Map(current);
        next.delete(profile.name);
        return next;
      });
    }
  };

  const toggleProfileRunning = (profile: ProfileSummary) => {
    if (profile.running || launchMode === "multi" || runningCount === 0) {
      void executeProfileToggle(profile);
      return;
    }

    Modal.confirm({
      title: t("确认切换账号"),
      content: language === "en-US"
        ? `ChatGPT is running. Close it and launch "${profile.name}"?`
        : `检测到 ChatGPT 正在运行。确认关闭当前 ChatGPT，并切换启动「${profile.name}」？`,
      okText: t("关闭并启动"),
      cancelText: t("取消"),
      onOk: () => executeProfileToggle(profile, true),
    });
  };

  const refreshAllUsage = async () => {
    setRefreshingAllUsage(true);
    try {
      await runCommand(
        "refresh_all_profile_usage",
        {},
        t("额度已刷新"),
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
        t("额度已刷新"),
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

  const chooseAuthJsonFile = async () => {
    const selectedPath = await window.launcherApi.selectAuthJsonFile();
    if (selectedPath) {
      setAuthJsonPath(selectedPath);
      createForm.setFields([
        { name: "authJsonPath", value: selectedPath, errors: [] },
      ]);
    }
  };

  const chooseBackupFile = async () => {
    const selectedPath = await window.launcherApi.selectProfileBackupFile?.();
    if (selectedPath) {
      setBackupPath(selectedPath);
      restoreForm.setFields([{ name: "backupPath", value: selectedPath, errors: [] }]);
    }
  };

  const loadProfileDetail = async (name: string, silent = false) => {
    if (!silent) {
      setDetailLoading(true);
    }
    try {
      setProfileDetail(await invokeLauncher<ProfileDetail>("get_profile_detail", { name }));
    } catch (error) {
      Modal.error({ title: t("读取账号详情失败"), content: error instanceof Error ? error.message : t("操作失败") });
    } finally {
      if (!silent) {
        setDetailLoading(false);
      }
    }
  };

  const openDetail = (profile: ProfileSummary) => {
    void loadProfileDetail(profile.name);
  };

  const exportBackup = async (profile: ProfileSummary) => {
    Modal.confirm({
      title: t("导出敏感账号备份"),
      content: t("备份包含 auth.json 和账号配置，请像密码一样妥善保管。会话、日志、缓存和客户端程序不会导出。"),
      okText: t("继续导出"),
      cancelText: t("取消"),
      onOk: async () => {
        const targetDir = await window.launcherApi.selectDirectory(profile.profileDir || undefined);
        if (!targetDir) {
          return;
        }
        await runCommand(
          "export_profile_backup",
          { name: profile.name, targetDir },
          t("账号备份已导出"),
          { blocking: false, refreshAfter: false },
        );
      },
    });
  };

  const refreshDetailUsage = async (profile: ProfileDetail) => {
    await refreshProfileUsage(profile);
    await loadProfileDetail(profile.name, true);
  };

  const accountHealth = profiles.reduce(
    (summary, profile) => {
      if (isHealthyProfile(profile)) {
        summary.healthy += 1;
      } else {
        summary.abnormal += 1;
      }
      return summary;
    },
    { total: profiles.length, healthy: 0, abnormal: 0 },
  );
  const recommendedProfileName = getRecommendedProfileName(profiles);

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-3 gap-3 max-[960px]:grid-cols-1">
        <StatusTile label={t("账号总数量")} value={accountHealth.total} tone="blue" />
        <StatusTile label={t("健康账号数量")} value={accountHealth.healthy} tone="green" />
        <StatusTile
          label={t("异常账号数量")}
          value={accountHealth.abnormal}
          tone={accountHealth.abnormal > 0 ? "red" : "green"}
        />
      </div>

      <div className="overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
        <div className="flex items-center justify-between gap-4 border-b border-[#ecf1f6] bg-white px-5 py-4 max-[960px]:items-start max-[960px]:flex-col">
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-extrabold leading-none text-gray-900">
              {profiles.length}
            </span>
            <span className="text-sm font-medium text-slate-500">{t("个账号")}</span>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2.5 max-[960px]:w-full max-[960px]:justify-start">
            <Button
              icon={<RefreshCw size={15} />}
              loading={refreshingAllUsage}
              disabled={pendingUsageProfileNames.size > 0}
              onClick={refreshAllUsage}
            >
              {t("刷新额度")}
            </Button>
            <Button
              icon={<Upload size={15} />}
              onClick={() => setRestoreOpen(true)}
            >
              {t("恢复备份")}
            </Button>
            <Button
              type="primary"
              icon={<Plus size={15} />}
              onClick={() => setCreateOpen(true)}
            >
              {t("新增账号")}
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
                  profile.active
                    ? `${profileRowBaseClass} bg-green-50/40 hover:bg-green-50/60`
                    : profileRowBaseClass
                }
              >
                <div
                  className={
                    profile.active
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
                    {profile.name === recommendedProfileName ? (
                      <span className={`${profilePillBaseClass} border-emerald-200 bg-emerald-50 text-emerald-600`}>
                        {t("推荐使用")}
                      </span>
                    ) : null}
                    <span
                      className={
                        profile.running
                          ? `${profilePillBaseClass} border-green-200 bg-green-50 text-green-600`
                          : `${profilePillBaseClass} border-slate-200 bg-slate-50 text-slate-500`
                      }
                    >
                      {profile.running ? t("运行中") : t("就绪")}
                    </span>
                    {!profile.authExists ? (
                      <span className={`${profilePillBaseClass} border-amber-200 bg-amber-50 text-amber-600`}>
                        {t("认证缺失")}
                      </span>
                    ) : null}
                    {profile.active ? (
                      <span className={`${profilePillBaseClass} border-blue-200 bg-blue-50 text-blue-600`}>
                        {t("当前账号")}
                      </span>
                    ) : null}
                    {launchMode === "multi" ? (
                      <span className={`${profilePillBaseClass} border-purple-200 bg-purple-50 text-purple-600`}>
                        {profile.portableCodexExists
                          ? `${language === "en-US" ? "App copy" : "程序副本"} ${profile.portableCodexSizeText ?? ""}`
                          : t("程序副本待创建")}
                      </span>
                    ) : null}
                  </div>
                  <Tooltip title={maskPath(profile.profileDir, privacyMode)} placement="topLeft">
                    <div className="truncate font-mono text-xs leading-normal text-slate-400">
                      {maskPath(profile.profileDir, privacyMode)}
                    </div>
                  </Tooltip>
                  <div className="mt-3 grid max-w-[520px] grid-cols-[max-content_minmax(108px,0.22fr)_minmax(108px,0.22fr)] items-center gap-3 max-[960px]:max-w-none max-[960px]:grid-cols-1">
                    <span className="inline-flex h-6 w-fit items-center justify-center justify-self-start whitespace-nowrap rounded-[6px] border border-blue-200 bg-blue-50 px-2 text-[11.5px] font-bold text-blue-600">
                      {formatPlanType(profile.usage?.planType, t)}
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
                          label={t("五小时")}
                          language={language}
                          window={profile.usage?.fiveHour ?? null}
                        />
                        <UsageMeter
                          label={t("一周")}
                          language={language}
                          window={profile.usage?.oneWeek ?? null}
                        />
                      </>
                    )}
                  </div>
                  {profile.usage?.fetchedAt ? (
                    <div className="mt-2 text-[11.5px] text-slate-400">
                      {t("最后刷新")}：{formatTimestamp(profile.usage.fetchedAt, language)}
                    </div>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center max-[960px]:items-end max-[960px]:flex-col">
                  <Space.Compact>
                    {(() => {
                      const isPending = pendingProfileNames.has(profile.name);
                      const pendingText = pendingProfileTexts.get(profile.name);
                      const launchText = getProfileLaunchText(
                        profile,
                        runningCount,
                        launchMode,
                        t,
                      );

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
                            ? pendingText ?? t("处理中")
                            : profile.running
                              ? t("关闭")
                              : launchText}
                        </Button>
                      );
                    })()}
                    <Tooltip title={t("刷新额度")}>
                      <Button
                        className={iconActionButtonClass}
                        icon={<RefreshCw size={14} />}
                        loading={pendingUsageProfileNames.has(profile.name)}
                        disabled={refreshingAllUsage}
                        onClick={() => refreshProfileUsage(profile)}
                      />
                    </Tooltip>
                    <Tooltip title={t("账号详情")}>
                      <Button
                        className={iconActionButtonClass}
                        icon={<Info size={14} />}
                        loading={detailLoading && profileDetail?.name === profile.name}
                        onClick={() => openDetail(profile)}
                      />
                    </Tooltip>
                    <Tooltip title={t("导出备份")}>
                      <Button
                        className={iconActionButtonClass}
                        icon={<Download size={14} />}
                        disabled={profile.running}
                        onClick={() => exportBackup(profile)}
                      />
                    </Tooltip>
                    <Tooltip title={t("改名")}>
                      <Button
                        className={iconActionButtonClass}
                        icon={<UserPen size={14} />}
                        disabled={profile.running}
                        onClick={() => setRenameTarget(profile)}
                      />
                    </Tooltip>
                    <Tooltip title={t("打开目录")}>
                      <Button
                        className={iconActionButtonClass}
                        icon={<FolderOpen size={14} />}
                        onClick={() =>
                          runCommand(
                            "open_path",
                            { path: profile.profileDir },
                            t("已打开目录"),
                            { blocking: false, refreshAfter: false },
                          )
                        }
                      />
                    </Tooltip>
                    <Tooltip title={t("删除")}>
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
              <Empty description={t("暂无账号")}>
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => setCreateOpen(true)}
                >
                  {t("新增第一个账号")}
                </Button>
              </Empty>
            </div>
          )}
        </div>
      </div>

      <Modal
        title={t("新增账号")}
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          setAuthJsonPath("");
          setCreateMode("oauth");
          createForm.resetFields();
        }}
        onOk={async () => {
          const values = await createForm.validateFields();
          if (createMode === "file" && !authJsonPath) {
            createForm.setFields([
              { name: "authJsonPath", errors: [t("请选择 auth.json 文件")] },
            ]);
            return;
          }
          setCreateOpen(false);
          const command =
            createMode === "oauth"
              ? "create_oauth_profile"
              : createMode === "file"
                ? "create_auth_file_profile"
                : "create_profile";
          await runCommand(
            command,
            createMode === "file" ? { ...values, authJsonPath } : values,
            createMode === "oauth"
              ? t("浏览器授权账号已新增")
              : createMode === "file"
                ? t("auth.json 已导入")
                : t("当前账号已导入"),
          );
          createForm.resetFields();
          setAuthJsonPath("");
          setCreateMode("oauth");
        }}
        okText={
          createMode === "oauth"
            ? t("打开浏览器授权")
            : createMode === "file"
              ? t("导入文件")
              : t("导入当前账号")
        }
      >
        <Form form={createForm} layout="vertical">
          <Form.Item label={t("新增方式")}>
            <Radio.Group
              value={createMode}
              onChange={(event) => setCreateMode(event.target.value)}
            >
              <Radio.Button value="oauth">{t("浏览器授权")}</Radio.Button>
              <Radio.Button value="current">{t("导入当前账号")}</Radio.Button>
              <Radio.Button value="file">{t("上传 auth.json")}</Radio.Button>
            </Radio.Group>
          </Form.Item>
          {createMode === "oauth" ? (
            <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
              {language === "en-US" ? "Open the official ChatGPT browser sign-in. The result is saved only to the new account profile and will not overwrite the current ChatGPT account." : "将打开 ChatGPT 官方浏览器登录，授权结果只保存到新账号资料目录，不会覆盖当前 ChatGPT 账号。"}
            </Typography.Paragraph>
          ) : createMode === "file" ? (
            <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
              {language === "en-US" ? "Choose a local " : "将从本地选择 "}<Typography.Text code>auth.json</Typography.Text>{language === "en-US" ? ". It is saved only to the new account profile and will not overwrite the current ChatGPT account." : "，只保存到新账号资料目录，不会覆盖当前 ChatGPT 账号。"}
            </Typography.Paragraph>
          ) : (
            <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
              {language === "en-US" ? "Save the current ChatGPT " : "将保存当前 ChatGPT 的 "}<Typography.Text code>auth.json</Typography.Text>{language === "en-US" ? ". The system " : "；系统 "}
              <Typography.Text code>config.toml</Typography.Text>{language === "en-US" ? " will be used as the initial isolated-mode config." : " 会作为多开隔离模式的初始账号配置。"}
            </Typography.Paragraph>
          )}
          <Form.Item
            name="name"
            label={t("账号名称")}
            rules={[{ required: true, message: t("请输入账号名称") }]}
          >
            <Input placeholder={t("例如：工作号")} />
          </Form.Item>
          {createMode === "file" ? (
            <Form.Item
              name="authJsonPath"
              label={t("认证文件")}
            >
              <Space.Compact className="w-full">
                <Input value={authJsonPath} readOnly placeholder={t("请选择 auth.json 文件")} />
                <Button icon={<FolderOpen size={15} />} onClick={chooseAuthJsonFile}>
                  {t("选择文件")}
                </Button>
              </Space.Compact>
            </Form.Item>
          ) : null}
        </Form>
      </Modal>
      <Modal
        title={t("修改账号名称")}
        open={Boolean(renameTarget)}
        onCancel={() => setRenameTarget(null)}
        onOk={async () => {
          const values = await renameForm.validateFields();
          const oldName = renameTarget?.name;
          await runCommand(
            "rename_profile",
            { oldName, newName: values.name },
            t("已修改账号名称"),
          );
          setRenameTarget(null);
          renameForm.resetFields();
        }}
      >
        <Form form={renameForm} layout="vertical">
          <Form.Item
            name="name"
            label={t("新名称")}
            rules={[{ required: true, message: t("请输入新名称") }]}
          >
            <Input />
          </Form.Item>
        </Form>
      </Modal>
      <Modal
        title={t("恢复账号备份")}
        open={restoreOpen}
        onCancel={() => {
          setRestoreOpen(false);
          setBackupPath("");
          restoreForm.resetFields();
        }}
        onOk={async () => {
          const values = await restoreForm.validateFields();
          if (!backupPath) {
            restoreForm.setFields([{ name: "backupPath", errors: [t("请选择账号备份文件")] }]);
            return;
          }
          setRestoreOpen(false);
          await runCommand(
            "import_profile_backup",
            { backupPath, name: values.name },
            t("账号备份已恢复"),
          );
          setBackupPath("");
          restoreForm.resetFields();
        }}
      >
        <Form form={restoreForm} layout="vertical">
          <Form.Item name="backupPath" label={t("备份文件")}>
            <Space.Compact className="w-full">
              <Input value={backupPath} readOnly placeholder={t("请选择账号备份文件")} />
              <Button icon={<Archive size={15} />} onClick={chooseBackupFile}>
                {t("选择文件")}
              </Button>
            </Space.Compact>
          </Form.Item>
          <Form.Item name="name" label={t("账号名称")} extra={t("留空则使用备份中的账号名称")}>
            <Input placeholder={t("例如：工作号")} />
          </Form.Item>
        </Form>
      </Modal>
      <Drawer
        title={null}
        open={Boolean(profileDetail)}
        width={760}
        onClose={() => setProfileDetail(null)}
        styles={{ body: { padding: 0 } }}
      >
        {profileDetail ? (
          <ProfileDetailPanel
            detail={profileDetail}
            language={language}
            privacyMode={privacyMode}
            t={t}
            onToggleRunning={toggleProfileRunning}
            onRefreshUsage={refreshDetailUsage}
            onExportBackup={exportBackup}
            onOpenPath={(path) =>
              runCommand(
                "open_path",
                { path },
                t("已打开目录"),
                { blocking: false, refreshAfter: false },
              )
            }
          />
        ) : null}
      </Drawer>
    </div>
  );
}

function ProfileDetailPanel({
  detail,
  language,
  privacyMode,
  t,
  onToggleRunning,
  onRefreshUsage,
  onExportBackup,
  onOpenPath,
}: {
  detail: ProfileDetail;
  language: "zh-CN" | "en-US";
  privacyMode: boolean;
  t: (text: string) => string;
  onToggleRunning: (profile: ProfileSummary) => void;
  onRefreshUsage: (profile: ProfileDetail) => Promise<void>;
  onExportBackup: (profile: ProfileSummary) => Promise<void>;
  onOpenPath: (path: string) => void;
}) {
  const authOk = detail.auth.exists && !detail.auth.error;
  const healthTone = authOk && detail.profileDirExists ? "green" : "amber";
  const planText = detail.auth.authMode === "api"
    ? "API Key"
    : formatPlanType(detail.auth.planType || detail.usage?.planType, t);
  const accountId = maskSensitive(detail.auth.accountId || "-", privacyMode);
  const email = maskSensitive(detail.auth.email || "-", privacyMode);

  return (
    <div className="min-h-full bg-[#f7f9fc]">
      <div className="border-b border-slate-200 bg-white px-6 pb-5 pt-6">
        <div className="flex items-start justify-between gap-5">
          <div className="flex min-w-0 items-start gap-4">
            <div className="grid h-14 w-14 shrink-0 place-items-center rounded-[14px] bg-slate-900 text-xl font-black text-white shadow-[0_12px_30px_rgba(15,23,42,0.22)]">
              {detail.name.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <h2 className="m-0 truncate text-xl font-extrabold leading-tight text-slate-950">
                  {detail.name}
                </h2>
                <StatusPill tone={healthTone} text={authOk ? t("认证正常") : t("需要处理")} />
                {detail.running ? <StatusPill tone="blue" text={t("运行中")} /> : null}
              </div>
              <div className="grid gap-1 text-sm text-slate-500">
                <span>{email}</span>
                <span className="font-mono text-xs">{accountId}</span>
              </div>
            </div>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <Button
              type="primary"
              danger={detail.running}
              icon={detail.running ? <Square size={15} /> : <Play size={15} />}
              onClick={() => onToggleRunning(detail)}
            >
              {detail.running ? t("关闭") : t("启动")}
            </Button>
            <Button
              icon={<RefreshCw size={15} />}
              disabled={detail.auth.authMode === "api"}
              onClick={() => void onRefreshUsage(detail)}
            >
              {t("刷新额度")}
            </Button>
            <Button icon={<Download size={15} />} disabled={detail.running} onClick={() => void onExportBackup(detail)}>
              {t("导出备份")}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid gap-4 p-6">
        <div className="grid grid-cols-3 gap-3 max-[960px]:grid-cols-1">
          <DetailMetric
            icon={<KeyRound size={17} />}
            label={t("认证状态")}
            value={authOk ? t("认证正常") : t("需要重新授权")}
            tone={authOk ? "green" : "amber"}
          />
          <DetailMetric
            icon={<WalletCards size={17} />}
            label={t("套餐")}
            value={planText}
            tone="blue"
          />
          <DetailMetric
            icon={<Archive size={17} />}
            label={t("程序副本")}
            value={detail.portableCodexExists ? detail.portableCodexSizeText || "0 B" : t("待创建")}
            tone={detail.portableCodexExists ? "green" : "slate"}
          />
        </div>

        <div className="rounded-[10px] border border-slate-200 bg-white px-5 py-4 shadow-sm">
          <Tabs
            defaultActiveKey="overview"
            items={[
              {
                key: "overview",
                label: t("概览"),
                children: (
                  <div className="grid gap-4">
                    {detail.auth.error ? (
                      <div className="flex gap-3 rounded-[8px] border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
                        <ShieldAlert size={18} className="mt-0.5 shrink-0" />
                        <span>{detail.auth.error}</span>
                      </div>
                    ) : null}
                    <div className="grid grid-cols-2 gap-3 max-[960px]:grid-cols-1">
                      <DetailUsageCard title={t("五小时额度")} language={language} window={detail.usage?.fiveHour ?? null} />
                      <DetailUsageCard title={t("一周额度")} language={language} window={detail.usage?.oneWeek ?? null} />
                    </div>
                    <InfoGrid
                      rows={[
                        [t("最后刷新"), detail.usage?.fetchedAt ? formatTimestamp(detail.usage.fetchedAt, language) : "-"],
                        [t("可用额度重置"), detail.usage?.resetCredits == null ? "-" : String(detail.usage.resetCredits)],
                        [t("额度模式"), detail.usage?.creditsUnlimited ? t("无限额度") : detail.usage?.hasCredits ? t("有可用额度") : t("无额外额度")],
                        [t("限制状态"), detail.usage?.rateLimitReachedType ? t("已触发") : t("未触发")],
                        [t("当前账号"), detail.active ? t("是") : t("否")],
                        [t("运行状态"), detail.running ? t("运行中") : t("就绪")],
                        [t("账号目录"), maskPath(detail.profileDir, privacyMode)],
                      ]}
                    />
                  </div>
                ),
              },
              {
                key: "auth",
                label: t("认证与额度"),
                children: (
                  <div className="grid gap-4">
                    <InfoGrid
                      rows={[
                        [t("认证方式"), detail.auth.authMode === "api" ? "API Key" : t("ChatGPT 登录")],
                        ["Email", email],
                        ["Account ID", accountId],
                        [t("套餐"), planText],
                        ["Access token", detail.auth.accessTokenExpiresAt ? `${t("过期时间")}：${formatTimestamp(detail.auth.accessTokenExpiresAt, language)}` : t("未返回")],
                        ["Refresh token", detail.auth.hasRefreshToken ? t("存在") : t("缺失")],
                      ]}
                    />
                    <div className="rounded-[8px] border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
                      {t("账号详情只展示认证元数据，不展示原始 token。")}
                    </div>
                  </div>
                ),
              },
              {
                key: "files",
                label: t("文件位置"),
                children: (
                  <div className="grid gap-3">
                    <PathRow label={t("账号目录")} path={detail.profileDir} privacyMode={privacyMode} t={t} onOpenPath={onOpenPath} />
                    <PathRow label="auth.json" path={detail.authPath} privacyMode={privacyMode} t={t} onOpenPath={onOpenPath} />
                    <PathRow label="config.toml" path={detail.configPath} privacyMode={privacyMode} t={t} onOpenPath={onOpenPath} />
                    {detail.codexHome ? (
                      <PathRow label="CodexHome" path={detail.codexHome} privacyMode={privacyMode} t={t} onOpenPath={onOpenPath} />
                    ) : null}
                    {detail.portableCodexPath ? (
                      <PathRow label={t("程序副本")} path={detail.portableCodexPath} privacyMode={privacyMode} t={t} onOpenPath={onOpenPath} />
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function DetailMetric({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone: "green" | "amber" | "blue" | "slate";
}) {
  const toneClass =
    tone === "green"
      ? "bg-emerald-50 text-emerald-700 ring-emerald-100"
      : tone === "amber"
        ? "bg-amber-50 text-amber-700 ring-amber-100"
        : tone === "blue"
          ? "bg-blue-50 text-blue-700 ring-blue-100"
          : "bg-slate-50 text-slate-600 ring-slate-100";
  return (
    <div className="rounded-[10px] border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="mb-3 flex items-center gap-2 text-[12px] font-semibold text-slate-500">
        <span className={`grid h-8 w-8 place-items-center rounded-[8px] ring-1 ${toneClass}`}>{icon}</span>
        {label}
      </div>
      <div className="truncate text-[15px] font-extrabold text-slate-900">{value}</div>
    </div>
  );
}

function StatusPill({ tone, text }: { tone: "green" | "amber" | "blue"; text: string }) {
  const toneClass =
    tone === "green"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : tone === "amber"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : "border-blue-200 bg-blue-50 text-blue-700";
  return <span className={`inline-flex h-6 items-center rounded-[7px] border px-2 text-[12px] font-bold ${toneClass}`}>{text}</span>;
}

function DetailUsageCard({
  title,
  language,
  window,
}: {
  title: string;
  language: "zh-CN" | "en-US";
  window: ProfileUsageWindow | null;
}) {
  const used = clampPercent(window?.usedPercent);
  const remainingText = formatPercent(window?.remainingPercent);
  const resetCountdown = formatResetCountdown(window?.resetAt, language);
  const barColor = used > 80 ? "bg-red-500" : used > 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="rounded-[9px] border border-slate-200 bg-white p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="font-bold text-slate-800">{title}</div>
        <div className="rounded-[7px] bg-slate-100 px-2 py-1 text-[12px] font-bold text-slate-700">{remainingText}</div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${used}%` }} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[12px] text-slate-500">
        <span>{formatPercent(window?.usedPercent)}</span>
        <span>{resetCountdown}</span>
      </div>
    </div>
  );
}

function InfoGrid({ rows }: { rows: Array<[string, string]> }) {
  return (
    <div className="grid overflow-hidden rounded-[9px] border border-slate-200 bg-white">
      {rows.map(([label, value]) => (
        <div key={label} className="grid grid-cols-[140px_minmax(0,1fr)] border-b border-slate-100 px-4 py-3 text-sm last:border-b-0 max-[720px]:grid-cols-1 max-[720px]:gap-1">
          <div className="font-semibold text-slate-500">{label}</div>
          <div className="min-w-0 break-words font-medium text-slate-800">{value}</div>
        </div>
      ))}
    </div>
  );
}

function PathRow({
  label,
  path,
  privacyMode,
  t,
  onOpenPath,
}: {
  label: string;
  path: string;
  privacyMode: boolean;
  t: (text: string) => string;
  onOpenPath: (path: string) => void;
}) {
  const visiblePath = maskPath(path, privacyMode);
  const copyPath = async () => {
    await navigator.clipboard.writeText(path);
    message.success(t("路径已复制"));
  };
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)_auto] items-center gap-3 rounded-[9px] border border-slate-200 bg-white px-4 py-3 max-[720px]:grid-cols-1">
      <div className="text-sm font-bold text-slate-600">{label}</div>
      <Tooltip title={visiblePath}>
        <div className="min-w-0 truncate font-mono text-xs text-slate-500">{visiblePath}</div>
      </Tooltip>
      <Space.Compact>
        <Button size="small" onClick={() => void copyPath()}>{t("复制")}</Button>
        <Button size="small" icon={<FolderOpen size={13} />} onClick={() => onOpenPath(path)}>{t("打开")}</Button>
      </Space.Compact>
    </div>
  );
}

function isHealthyProfile(profile: ProfileSummary) {
  return profile.profileDirExists && profile.authExists;
}

function getProfileLaunchText(
  profile: ProfileSummary,
  runningCount: number,
  launchMode: "switch" | "multi",
  t: (text: string) => string,
) {
  if (profile.running) {
    return t("关闭");
  }

  if (launchMode === "multi") {
    return t("启动");
  }

  return runningCount > 0 ? t("切换") : t("启动");
}

function StatusTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone: "blue" | "green" | "amber" | "red";
}) {
  const toneClass =
    tone === "green"
      ? "border-emerald-100 bg-emerald-50 text-emerald-700"
      : tone === "red"
        ? "border-red-100 bg-red-50 text-red-700"
      : tone === "amber"
        ? "border-amber-100 bg-amber-50 text-amber-700"
        : "border-blue-100 bg-blue-50 text-blue-700";

  return (
    <div className="rounded-card border border-shell-line bg-white px-4 py-3">
      <span className="block text-[12px] font-semibold text-shell-muted">
        {label}
      </span>
      <strong className={`mt-2 inline-flex min-h-7 items-center rounded-[7px] border px-2.5 text-sm ${toneClass}`}>
        {value}
      </strong>
    </div>
  );
}

function UsageMeter({
  label,
  language,
  window,
}: {
  label: string;
  language: "zh-CN" | "en-US";
  window: ProfileUsageWindow | null;
}) {
  const usedText = formatPercent(window?.usedPercent);
  const remainingText = formatPercent(window?.remainingPercent);
  const resetText = formatResetAt(window?.resetAt, language);
  const countdownText = formatResetCountdown(window?.resetAt, language);

  const percent = clampPercent(window?.usedPercent);
  let barColor = "bg-green-500";
  if (percent > 80) barColor = "bg-red-500";
  else if (percent > 50) barColor = "bg-amber-500";

  return (
    <Tooltip
      title={language === "en-US"
        ? `Used ${usedText}, remaining ${remainingText}, resets ${countdownText} (${resetText})`
        : `已用 ${usedText}，剩余 ${remainingText}，${countdownText}重置（${resetText}）`}
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

function formatPlanType(planType: string | null | undefined, t: (text: string) => string) {
  const normalized = planType?.trim().toLowerCase();
  if (normalized === "free") return t("免费版");
  if (normalized === "plus") return t("增强版");
  if (normalized === "pro") return t("专业版");
  if (normalized === "team") return t("团队版");
  if (normalized === "enterprise") return t("企业版");
  if (normalized === "business") return t("商业版");
  return t("套餐未识别");
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

function formatResetAt(value: number | null | undefined, language: "zh-CN" | "en-US") {
  if (!value) {
    return language === "en-US" ? "Not returned" : "未返回";
  }
  return new Date(value * 1000).toLocaleString(language);
}

function formatTimestamp(value: number | null | undefined, language: "zh-CN" | "en-US") {
  if (!value) {
    return "-";
  }
  return new Date(value * 1000).toLocaleString(language);
}

function formatResetCountdown(value: number | null | undefined, language: "zh-CN" | "en-US") {
  if (!value) {
    return language === "en-US" ? "at unknown time" : "未知时间";
  }
  const seconds = Math.max(0, value - Math.floor(Date.now() / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (language === "en-US") {
    return hours > 0 ? `in ${hours}h ${minutes}m` : `in ${minutes}m`;
  }
  return hours > 0 ? `${hours}小时${minutes}分钟后` : `${minutes}分钟后`;
}

function getRecommendedProfileName(profiles: ProfileSummary[]) {
  let best: { name: string; score: number } | null = null;
  for (const profile of profiles) {
    if (!profile.authExists || profile.usage?.error) {
      continue;
    }
    const score = usageScore(profile.usage);
    if (!best || score > best.score) {
      best = { name: profile.name, score };
    }
  }
  return best?.name ?? "";
}

function usageScore(usage: ProfileUsage | null) {
  if (!usage) {
    return -1;
  }
  return Math.min(
    usage.fiveHour?.remainingPercent ?? 0,
    usage.oneWeek?.remainingPercent ?? 0,
  );
}

function maskSensitive(value: string, enabled: boolean) {
  if (!enabled || !value || value === "-") {
    return value;
  }
  if (value.includes("@")) {
    const [name, domain] = value.split("@");
    return `${name.slice(0, 2)}***@${domain}`;
  }
  return value.length <= 8 ? "***" : `${value.slice(0, 4)}***${value.slice(-4)}`;
}

function maskPath(value: string, enabled: boolean) {
  if (!enabled) {
    return value;
  }
  return value.replace(/C:\\Users\\[^\\/]+/gi, "C:\\Users\\<user>");
}
