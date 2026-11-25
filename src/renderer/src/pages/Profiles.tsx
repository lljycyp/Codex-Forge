import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Button,
  Drawer,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Radio,
  Segmented,
  Select,
  Space,
  Spin,
  Tabs,
  Tooltip,
  Typography,
} from "antd";
import {
  Archive,
  ChevronRight,
  Download,
  FolderOpen,
  Info,
  KeyRound,
  MonitorUp,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Square,
  Trash2,
  Upload,
  UserPen,
  WalletCards,
} from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";
import type { AppState, ProfileSummary, ProfileUsage, ProfileUsageWindow, ResetCredit, RunCommand } from "../types";

type ProfilesProps = {
  profiles: ProfileSummary[];
  runningCount: number;
  systemAuthMode: AppState["systemAuthMode"];
  runCommand: RunCommand;
  onUsageUpdated: (profileId: string, usage: ProfileUsage) => void;
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

type ResetAttempt = {
  attemptId: string;
  scope: string;
  credit: ResetCredit | null;
  workspaceName?: string | null;
};

type ResetResult = {
  outcome: "reset" | "alreadyRedeemed" | "nothingToReset" | "noCredit" | "creditUnavailable" | "chooseCredit" | "accountChanged" | "unsupported" | "unavailable";
  usage?: ProfileUsage;
};

const resetAttemptsKey = "codexForge.resetAttempts";

function readResetAttempts(): Record<string, ResetAttempt> {
  try {
    const saved = JSON.parse(localStorage.getItem(resetAttemptsKey) || "{}");
    return saved && typeof saved === "object" ? saved : {};
  } catch {
    return {};
  }
}

const profileRowBaseClass =
  "relative grid cursor-pointer grid-cols-[minmax(150px,1fr)_minmax(150px,0.62fr)_auto] items-center gap-3 overflow-hidden rounded-[10px] border border-slate-200/80 bg-white px-3.5 py-3 transition-[border-color,background-color,box-shadow] duration-200 hover:border-slate-300 hover:shadow-[0_5px_16px_rgba(15,23,42,0.04)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 max-[960px]:grid-cols-1";

const profilePillBaseClass =
  "inline-flex h-[22px] items-center rounded-[6px] px-2 text-[11.5px] font-bold leading-none border";

export function Profiles({ profiles, runningCount, systemAuthMode, runCommand, onUsageUpdated, loading }: ProfilesProps) {
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
  const [resetAttempts, setResetAttempts] = useState(readResetAttempts);
  const [detailLoading, setDetailLoading] = useState(false);
  const [profileDetail, setProfileDetail] = useState<ProfileDetail | null>(null);
  const [selectedProfileName, setSelectedProfileName] = useState("");
  const [profileSearch, setProfileSearch] = useState("");
  const [profileFilter, setProfileFilter] = useState<"all" | "running" | "attention">("all");
  const [profileSort, setProfileSort] = useState<"recommended" | "usage" | "name">("recommended");
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
    const hasRunningCodex = runningCount > 0;
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
          ? t("已关闭 Codex")
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
    if (profile.running || runningCount === 0) {
      void executeProfileToggle(profile);
      return;
    }

    Modal.confirm({
      title: t("确认切换账号"),
      content: language === "en-US"
        ? `Codex is running. Close it and launch "${profile.name}"?`
        : `检测到 Codex 正在运行。确认关闭当前 Codex，并切换启动「${profile.name}」？`,
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

  const confirmResetCredit = (profile: ProfileSummary, credit: ResetCredit | null) => {
    const pending = resetAttempts[profile.id];
    const scope = pending?.scope ?? profile.usage?.resetAccountScope;
    if (!scope) return;

    const attempt = pending ?? {
      attemptId: crypto.randomUUID(),
      scope,
      credit,
      workspaceName: profile.usage?.workspaceName,
    };
    const saveAttempt = (value: ResetAttempt | null) => {
      const stored = readResetAttempts();
      if (value) stored[profile.id] = value;
      else delete stored[profile.id];
      localStorage.setItem(resetAttemptsKey, JSON.stringify(stored));
      setResetAttempts(stored);
    };

    Modal.confirm({
      title: t(pending ? "重试重置额度" : "确认重置额度"),
      content: (
        <div className="grid gap-2">
          <div>{t("账号")} · {profile.name}</div>
          {attempt.workspaceName ? <div>{t("工作区")} · {attempt.workspaceName}</div> : null}
          {attempt.credit ? <div>{t("所选卡到期时间")} · {attempt.credit.expiresAt == null ? t("无到期时间") : formatTimestamp(attempt.credit.expiresAt, language)}</div> : null}
          <div>{t(pending ? "将核对上次重置结果，已完成的操作不会再次扣次。" : "将消耗 1 次重置权益。")}</div>
        </div>
      ),
      okText: t(pending ? "重试" : "确认重置"),
      cancelText: t("取消"),
      onOk: async () => {
        try {
          saveAttempt(attempt);
          const result = await invokeLauncher<ResetResult>("reset_profile_usage", {
            name: profile.name,
            profileId: profile.id,
            scope: attempt.scope,
            attemptId: attempt.attemptId,
            creditId: attempt.credit?.id ?? null,
            retry: Boolean(pending),
          });
          saveAttempt(null);
          if (result.usage) onUsageUpdated(profile.id, result.usage);
          if (result.outcome === "reset" || result.outcome === "alreadyRedeemed") {
            if (result.usage?.error) message.warning(t("重置成功，额度待更新。请重新查询额度。"));
            else message.success(t("Codex 额度已重置"));
            return;
          }
          const notices = {
            nothingToReset: "当前没有可重置的额度窗口",
            noCredit: "该账号没有可用的重置次数",
            creditUnavailable: "所选卡已不可用，请重新选择",
            chooseCredit: "已取得卡片明细，请选择一张使用",
            accountChanged: "账号认证已变化，请重新查询额度后再选择",
            unsupported: "当前 Codex 版本不支持重置额度，请更新 Codex",
            unavailable: "暂时无法核对重置权益，请重新查询额度",
          };
          message.warning(t(notices[result.outcome]));
        } catch {
          message.error(t("未能确认重置结果，请重试同一次操作"));
        }
      },
    });
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
      title: t("导出加密账号备份"),
      content: t("备份包含 auth.json 和账号配置，并使用当前 Windows 用户加密。它只能由创建备份的 Windows 用户恢复；会话、日志、缓存和客户端程序不会导出。"),
      okText: t("继续导出"),
      cancelText: t("取消"),
      onOk: async () => {
        const targetDir = await window.launcherApi.selectDirectory(profile.profileDir || undefined);
        if (!targetDir) {
          return;
        }
        await runCommand(
          "export_profile_backup",
          { name: profile.name, targetDir, secure: true },
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

  const abnormalProfileCount = profiles.reduce(
    (count, profile) => count + (isHealthyProfile(profile) ? 0 : 1),
    0,
  );
  const recommendedProfileName = getRecommendedProfileName(profiles);
  const runningProfiles = profiles.filter((profile) => profile.running);
  const detailProfile = profiles.find((profile) => profile.id === profileDetail?.id);
  const currentDetail = profileDetail && detailProfile
    ? { ...profileDetail, active: detailProfile.active, running: detailProfile.running }
    : profileDetail;
  const selectedProfile =
    profiles.find((profile) => profile.name === selectedProfileName)
    ?? profiles.find((profile) => profile.running)
    ?? profiles.find((profile) => profile.active)
    ?? profiles.find((profile) => profile.name === recommendedProfileName)
    ?? profiles[0]
    ?? null;
  const visibleProfiles = useMemo(() => {
    const search = profileSearch.trim().toLowerCase();
    return profiles
      .filter((profile) => {
        if (profileFilter === "running" && !profile.running) return false;
        if (profileFilter === "attention" && isHealthyProfile(profile) && !profile.usage?.error) return false;
        return !search || profile.name.toLowerCase().includes(search);
      })
      .sort((left, right) => {
        if (profileSort === "name") return left.name.localeCompare(right.name);
        if (profileSort === "usage") return usageScore(right.usage) - usageScore(left.usage);
        return compareRecommendedProfiles(left, right);
      });
  }, [profileFilter, profileSearch, profileSort, profiles]);

  return (
    <div className="mx-auto grid w-full max-w-[1480px] gap-4">
      <RuntimeWorkspace
        runningProfiles={runningProfiles}
        runningCount={runningCount}
        systemAuthMode={systemAuthMode}
        abnormalCount={abnormalProfileCount}
        t={t}
        onSelectProfile={setSelectedProfileName}
      />

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(290px,320px)] items-start gap-4 max-[1050px]:grid-cols-1">
        <section className="overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]" aria-label={t("账号库")}>
          <div className="flex items-center justify-between gap-4 border-b border-[#e8edf3] px-5 py-3.5 max-[960px]:items-start max-[960px]:flex-col">
            <div>
              <div className="flex items-baseline gap-2">
                <h3 className="m-0 text-[16px] font-extrabold text-slate-900">{t("账号库")}</h3>
                <span className="text-[12px] font-semibold text-slate-400 tabular-nums">{profiles.length}</span>
              </div>
              <div className="mt-1 text-[12px] text-slate-500 max-[1280px]:hidden">{t("选择账号后可在右侧查看和维护")}</div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 max-[960px]:justify-start">
              <Button aria-label={t("刷新额度")} icon={<RefreshCw size={14} />} loading={refreshingAllUsage} disabled={pendingUsageProfileNames.size > 0} onClick={refreshAllUsage}>
                <span className="max-[1280px]:hidden">{t("刷新额度")}</span>
              </Button>
              <Button aria-label={t("恢复备份")} icon={<Upload size={14} />} onClick={() => setRestoreOpen(true)}><span className="max-[1280px]:hidden">{t("恢复备份")}</span></Button>
              <Button type="primary" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>{t("新增账号")}</Button>
            </div>
          </div>

          <div className="grid grid-cols-[minmax(180px,1fr)_auto_126px] items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-4 py-2.5 max-[1280px]:grid-cols-[minmax(0,1fr)_126px]">
            <Input
              className="min-w-0 max-[1280px]:col-span-2"
              allowClear
              prefix={<Search size={14} className="text-slate-400" />}
              placeholder={t("搜索账号")}
              value={profileSearch}
              onChange={(event) => setProfileSearch(event.target.value)}
            />
            <Segmented
              value={profileFilter}
              onChange={(value) => setProfileFilter(value as "all" | "running" | "attention")}
              options={[
                { label: t("全部"), value: "all" },
                { label: t("运行中"), value: "running" },
                { label: t("需处理"), value: "attention" },
              ]}
            />
            <Select
              className="w-full"
              value={profileSort}
              onChange={setProfileSort}
              options={[
                { label: t("推荐优先"), value: "recommended" },
                { label: t("额度优先"), value: "usage" },
                { label: t("名称排序"), value: "name" },
              ]}
            />
          </div>

          <div className="relative grid gap-2 bg-[#f8fafb] p-2.5">
            {loading && profiles.length === 0 ? (
              <div className="flex min-h-[220px] items-center justify-center px-6 py-8"><Spin /></div>
            ) : visibleProfiles.length ? (
              visibleProfiles.map((profile) => {
                const isSelected = selectedProfile?.name === profile.name;
                const isPending = pendingProfileNames.has(profile.name);
                const launchText = getProfileLaunchText(profile, runningCount, t);
                return (
                  <article
                    key={profile.name}
                    role="button"
                    tabIndex={0}
                    aria-pressed={isSelected}
                    className={isSelected ? `${profileRowBaseClass} border-brand-200 bg-brand-50/50 shadow-[0_5px_16px_rgba(13,148,136,0.07)]` : profileRowBaseClass}
                    onClick={() => setSelectedProfileName(profile.name)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") setSelectedProfileName(profile.name);
                    }}
                  >
                    <span className={`absolute inset-y-3 left-0 w-[3px] rounded-r-full ${profile.running ? "bg-emerald-500" : isSelected ? "bg-brand-600" : "bg-slate-200"}`} aria-hidden />
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="min-w-0 truncate text-[14px] font-bold tracking-[-0.01em] text-slate-900">{profile.name}</span>
                        <span className="inline-flex h-[21px] items-center rounded-[6px] bg-blue-50 px-2 text-[11px] font-bold text-blue-600">{formatPlanType(profile.usage?.planType, t)}</span>
                        {profile.name === recommendedProfileName ? <span className={`${profilePillBaseClass} border-emerald-200 bg-emerald-50 text-emerald-600`}>{t("推荐使用")}</span> : null}
                      </div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-[11.5px] text-slate-500">
                        <span className={profile.running ? "font-semibold text-emerald-600" : ""}>{profile.running ? t("运行中") : t("就绪")}</span>
                        {!profile.authExists ? <span className="font-semibold text-amber-600">{t("认证缺失")}</span> : null}
                        {profile.active ? <span className="font-semibold text-blue-600">{t("当前账号")}</span> : null}
                      </div>
                    </div>
                    <div className="grid min-w-0 gap-2">
                      {profile.usage?.oneWeek ? <UsageMeter label={t("一周")} language={language} window={profile.usage.oneWeek} /> : null}
                      {profile.usage?.fiveHours ? <UsageMeter label={t("5 小时")} language={language} window={profile.usage.fiveHours} /> : null}
                      <ResetCreditSummary usage={profile.usage} language={language} compact />
                    </div>
                    <Button
                      className="!min-w-[86px] !rounded-[8px]"
                      type="primary"
                      danger={profile.running}
                      icon={profile.running ? <Square size={13} /> : <Play size={13} />}
                      loading={isPending}
                      disabled={isPending}
                      onClick={(event) => {
                        event.stopPropagation();
                        setSelectedProfileName(profile.name);
                        toggleProfileRunning(profile);
                      }}
                    >
                      {isPending ? pendingProfileTexts.get(profile.name) ?? t("处理中") : profile.running ? t("关闭") : launchText}
                    </Button>
                  </article>
                );
              })
            ) : (
              <div className="flex min-h-[220px] items-center justify-center px-6 py-8">
                <Empty description={profiles.length ? t("没有匹配的账号") : t("暂无账号")}>
                  {!profiles.length ? <Button type="primary" icon={<Plus size={16} />} onClick={() => setCreateOpen(true)}>{t("新增第一个账号")}</Button> : null}
                </Empty>
              </div>
            )}
          </div>
        </section>

        <aside className="sticky top-0 min-w-0 overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)] max-[1050px]:static" aria-label={t("账号检查器")}>
          <ProfileInspector
            profile={selectedProfile}
            recommendedProfileName={recommendedProfileName}
            language={language}
            t={t}
            refreshing={selectedProfile ? pendingUsageProfileNames.has(selectedProfile.name) : false}
            refreshingAllUsage={refreshingAllUsage}
            resetPending={selectedProfile ? Boolean(resetAttempts[selectedProfile.id]) : false}
            detailLoading={detailLoading}
            onToggleRunning={toggleProfileRunning}
            onRefreshUsage={refreshProfileUsage}
            onResetCredit={confirmResetCredit}
            onOpenDetail={openDetail}
            onExportBackup={exportBackup}
            onRename={setRenameTarget}
            onDelete={confirmDelete}
            onOpenPath={(path) => runCommand("open_path", { path }, t("已打开目录"), { blocking: false, refreshAfter: false })}
          />
        </aside>
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
              {language === "en-US" ? "Open the official Codex browser sign-in. The result is saved only to the new account profile and will not overwrite the current Codex account." : "将打开 Codex 官方浏览器登录，授权结果只保存到新账号资料目录，不会覆盖当前 Codex 账号。"}
            </Typography.Paragraph>
          ) : createMode === "file" ? (
            <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
              {language === "en-US" ? "Choose a local " : "将从本地选择 "}<Typography.Text code>auth.json</Typography.Text>{language === "en-US" ? ". It is saved only to the new account profile and will not overwrite the current Codex account." : "，只保存到新账号资料目录，不会覆盖当前 Codex 账号。"}
            </Typography.Paragraph>
          ) : (
            <Typography.Paragraph className="!mt-0 text-sm text-slate-500">
              {language === "en-US" ? "Save the current Codex " : "将保存当前 Codex 的 "}<Typography.Text code>auth.json</Typography.Text>{language === "en-US" ? ". The system " : "；系统 "}
              <Typography.Text code>config.toml</Typography.Text>{language === "en-US" ? " will be copied as the initial account configuration." : " 会作为初始账号配置。"}
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
        {currentDetail ? (
          <ProfileDetailPanel
            detail={currentDetail}
            language={language}
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

function RuntimeWorkspace({
  runningProfiles,
  runningCount,
  systemAuthMode,
  abnormalCount,
  t,
  onSelectProfile,
}: {
  runningProfiles: ProfileSummary[];
  runningCount: number;
  systemAuthMode: AppState["systemAuthMode"];
  abnormalCount: number;
  t: (text: string) => string;
  onSelectProfile: (name: string) => void;
}) {
  return (
    <section className="grid grid-cols-[minmax(250px,0.8fr)_minmax(0,1.35fr)_168px] overflow-hidden rounded-panel border border-shell-line bg-[linear-gradient(115deg,rgba(238,252,248,0.9),#fff_45%)] shadow-[0_8px_24px_rgba(15,23,42,0.04)] max-[960px]:grid-cols-1" aria-label={t("运行工作台")}>
      <div className="flex items-center gap-3.5 border-r border-slate-100 px-4 py-3.5 max-[960px]:border-b max-[960px]:border-r-0">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[9px] bg-slate-900 text-white shadow-[0_7px_16px_rgba(15,23,42,0.15)]">
          <MonitorUp size={17} />
        </span>
        <div className="min-w-0">
          <div className="text-[10.5px] font-bold tracking-[0.08em] text-slate-400">{t("当前模式")}</div>
          <div className="mt-0.5 truncate text-[14px] font-extrabold text-slate-900">{t("账号切换模式")}</div>
          <div className="mt-0.5 truncate text-[11px] text-slate-500">
            {t("单实例共用系统配置")}
          </div>
        </div>
      </div>
      <div className="flex min-w-0 flex-col justify-center px-4 py-3.5 max-[960px]:border-b max-[960px]:border-slate-100">
          <div className="text-[10.5px] font-bold tracking-[0.06em] text-slate-400">{t("当前 Codex 实例")}</div>
          <div className="mt-1.5 flex flex-wrap gap-2">
            {runningProfiles.length ? runningProfiles.map((profile) => (
              <button
                key={profile.name}
                className="inline-flex max-w-[280px] items-center gap-2 rounded-[7px] border border-emerald-200 bg-emerald-50/80 px-2.5 py-1.5 text-left text-[12px] font-semibold text-emerald-700 transition-colors hover:border-emerald-300 hover:bg-emerald-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-500"
                onClick={() => onSelectProfile(profile.name)}
              >
                <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.13)]" />
                <span className="truncate">{profile.name}</span>
              </button>
            )) : runningCount ? (
              <StatusPill tone="green" text={t(systemAuthMode === "api" ? "API Key 登录" : "系统 Codex")} />
            ) : (
              <span className="text-[13px] font-medium text-slate-400">{t("暂无运行实例")}</span>
            )}
          </div>
      </div>
      <div className="grid grid-cols-2 gap-2 border-l border-slate-100 px-3 py-3.5 max-[960px]:border-l-0">
        <RuntimeMetric label={t("运行中")} value={runningCount} tone={runningCount ? "green" : "slate"} />
        <RuntimeMetric label={t("需处理")} value={abnormalCount} tone={abnormalCount ? "red" : "slate"} />
      </div>
    </section>
  );
}

function RuntimeMetric({ label, value, tone }: { label: string; value: number; tone: "green" | "red" | "slate" }) {
  const toneClass = tone === "green" ? "text-emerald-700" : tone === "red" ? "text-red-600" : "text-slate-500";
  return (
    <div className="grid min-w-0 place-items-center rounded-[8px] bg-white/80 px-2 py-2 ring-1 ring-inset ring-slate-100">
      <strong className={`text-[18px] font-extrabold leading-none tabular-nums ${toneClass}`}>{value}</strong>
      <span className="mt-1 whitespace-nowrap text-[10.5px] font-semibold text-slate-400">{label}</span>
    </div>
  );
}

function ProfileInspector({
  profile,
  recommendedProfileName,
  language,
  t,
  refreshing,
  refreshingAllUsage,
  resetPending,
  detailLoading,
  onToggleRunning,
  onRefreshUsage,
  onResetCredit,
  onOpenDetail,
  onExportBackup,
  onRename,
  onDelete,
  onOpenPath,
}: {
  profile: ProfileSummary | null;
  recommendedProfileName: string;
  language: "zh-CN" | "en-US";
  t: (text: string) => string;
  refreshing: boolean;
  refreshingAllUsage: boolean;
  resetPending: boolean;
  detailLoading: boolean;
  onToggleRunning: (profile: ProfileSummary) => void;
  onRefreshUsage: (profile: ProfileSummary) => Promise<void>;
  onResetCredit: (profile: ProfileSummary, credit: ResetCredit | null) => void;
  onOpenDetail: (profile: ProfileSummary) => void;
  onExportBackup: (profile: ProfileSummary) => Promise<void>;
  onRename: (profile: ProfileSummary) => void;
  onDelete: (profile: ProfileSummary) => void;
  onOpenPath: (path: string) => void;
}) {
  if (!profile) {
    return <div className="grid min-h-[360px] place-items-center px-6 py-8"><Empty description={t("选择账号查看详情")} /></div>;
  }

  const healthy = isHealthyProfile(profile) && !profile.usage?.error;
  const isRecommended = profile.name === recommendedProfileName;
  const launchText = profile.running ? t("关闭") : t("切换");
  const openProfilePath = () => onOpenPath(profile.profileDir);

  return (
    <div className="min-w-0 bg-white">
      <div className="border-b border-slate-100 px-4 pb-3.5 pt-4">
        <div className="min-w-0">
          <div className="text-[11px] font-bold tracking-[0.08em] text-slate-400">{t("账号检查器")}</div>
          <Tooltip title={profile.name}>
            <h3 className="mb-0 mt-1.5 truncate text-[15px] font-extrabold text-slate-900">{profile.name}</h3>
          </Tooltip>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusPill tone={healthy ? "green" : "amber"} text={healthy ? t("认证正常") : t("需要处理")} />
            {profile.running ? <StatusPill tone="blue" text={t("运行中")} /> : null}
            {isRecommended ? <StatusPill tone="green" text={t("推荐使用")} /> : null}
          </div>
        </div>
        <Button className="!mt-3 !w-full" type="primary" danger={profile.running} icon={profile.running ? <Square size={13} /> : <Play size={13} />} onClick={() => onToggleRunning(profile)}>
          {launchText}
        </Button>
      </div>

      <Tabs
        className="min-w-0 px-4 [&_.ant-tabs-nav]:!mb-3"
        defaultActiveKey="overview"
        items={[
          {
            key: "overview",
            label: t("概览"),
            children: (
              <div className="grid gap-4 pb-4">
                {profile.usage?.error ? (
                  <div className="flex gap-2 rounded-[8px] border border-amber-200 bg-amber-50 px-3 py-2.5 text-[12px] text-amber-700">
                    <ShieldAlert size={15} className="mt-0.5 shrink-0" />
                    <span>{profile.usage.error}</span>
                  </div>
                ) : null}
                <div className="grid gap-3">
                  {profile.usage?.oneWeek ? <UsageMeter label={t("一周额度")} language={language} window={profile.usage.oneWeek} /> : null}
                  {profile.usage?.fiveHours ? <UsageMeter label={t("5 小时额度")} language={language} window={profile.usage.fiveHours} /> : null}
                  <ResetCreditSummary
                    usage={profile.usage}
                    language={language}
                    onUseCredit={(credit) => onResetCredit(profile, credit)}
                    disabled={refreshing || refreshingAllUsage}
                    resetPending={resetPending}
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <InspectorStat label={t("套餐")} value={formatPlanType(profile.usage?.planType, t)} />
                  <InspectorStat label={t("运行状态")} value={profile.running ? t("运行中") : t("就绪")} />
                  <InspectorStat label={t("认证状态")} value={profile.authExists ? t("认证正常") : t("认证缺失")} />
                  <InspectorStat label={t("当前账号")} value={profile.active ? t("是") : t("否")} />
                </div>
                <Button icon={<RefreshCw size={14} />} loading={refreshing} onClick={() => void onRefreshUsage(profile)}>{t("查询额度")}</Button>
              </div>
            ),
          },
          {
            key: "environment",
            label: t("运行环境"),
            children: (
              <div className="grid gap-2.5 pb-4">
                <InspectorRow label={t("账号目录")} value={profile.profileDir} />
                <InspectorRow label="auth.json" value={profile.authExists ? t("存在") : t("缺失")} />
                <InspectorRow label="config.toml" value={profile.configExists ? t("存在") : t("缺失")} />
                <Button icon={<FolderOpen size={14} />} onClick={openProfilePath}>{t("打开目录")}</Button>
                <Button icon={<Info size={14} />} loading={detailLoading} onClick={() => onOpenDetail(profile)}>{t("查看完整详情")}</Button>
              </div>
            ),
          },
          {
            key: "maintenance",
            label: t("维护操作"),
            children: (
              <div className="grid gap-2.5 pb-4">
                <Button icon={<Download size={14} />} disabled={profile.running} onClick={() => void onExportBackup(profile)}>{t("导出备份")}</Button>
                <Button icon={<UserPen size={14} />} disabled={profile.running} onClick={() => onRename(profile)}>{t("改名")}</Button>
                <Button icon={<FolderOpen size={14} />} onClick={openProfilePath}>{t("打开目录")}</Button>
                <Button danger icon={<Trash2 size={14} />} onClick={() => onDelete(profile)}>{t("删除账号")}</Button>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

function InspectorStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[8px] bg-slate-50 px-3 py-2.5 ring-1 ring-inset ring-slate-100">
      <div className="text-[10.5px] font-semibold text-slate-400">{label}</div>
      <div className="mt-1 truncate text-[12px] font-bold text-slate-700">{value}</div>
    </div>
  );
}

function InspectorRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-[8px] border border-slate-100 bg-slate-50/70 px-3 py-2.5">
      <div className="text-[10.5px] font-semibold text-slate-400">{label}</div>
      <Tooltip title={value}><div className="mt-1 truncate font-mono text-[11.5px] font-medium text-slate-600">{value}</div></Tooltip>
    </div>
  );
}

function ProfileDetailPanel({
  detail,
  language,
  t,
  onToggleRunning,
  onRefreshUsage,
  onExportBackup,
  onOpenPath,
}: {
  detail: ProfileDetail;
  language: "zh-CN" | "en-US";
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
  const accountId = detail.auth.accountId || "-";
  const email = detail.auth.email || "-";

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
        <div className="grid grid-cols-2 gap-3 max-[960px]:grid-cols-1">
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
                    <div className="grid gap-3">
                      {detail.usage?.oneWeek ? <DetailUsageCard title={t("一周额度")} language={language} window={detail.usage.oneWeek} /> : null}
                      {detail.usage?.fiveHours ? <DetailUsageCard title={t("5 小时额度")} language={language} window={detail.usage.fiveHours} /> : null}
                    </div>
                    <InfoGrid
                      rows={[
                        [t("最后刷新"), detail.usage?.fetchedAt ? formatTimestamp(detail.usage.fetchedAt, language) : "-"],
                        [t("可刷新次数"), detail.usage?.resetCredits == null ? "-" : String(detail.usage.resetCredits)],
                        [t("刷新次数过期"), formatCreditExpiries(detail.usage?.resetCreditExpiresAt, language)],
                        [t("额度模式"), detail.usage?.creditsUnlimited ? t("无限额度") : detail.usage?.hasCredits ? t("有可用额度") : t("无额外额度")],
                        [t("限制状态"), detail.usage?.rateLimitReachedType ? t("已触发") : t("未触发")],
                        [t("当前账号"), detail.active ? t("是") : t("否")],
                        [t("运行状态"), detail.running ? t("运行中") : t("就绪")],
                        [t("账号目录"), detail.profileDir],
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
                        [t("认证方式"), detail.auth.authMode === "api" ? "API Key" : t("Codex 登录")],
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
                    <PathRow label={t("账号目录")} path={detail.profileDir} t={t} onOpenPath={onOpenPath} />
                    <PathRow label="auth.json" path={detail.authPath} t={t} onOpenPath={onOpenPath} />
                    <PathRow label="config.toml" path={detail.configPath} t={t} onOpenPath={onOpenPath} />
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
  const remaining = clampPercent(window?.remainingPercent);
  const remainingText = formatPercent(window?.remainingPercent);
  const resetCountdown = formatResetCountdown(window?.resetAt, language);
  const barColor = remaining <= 20 ? "bg-red-500" : remaining <= 50 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="rounded-[9px] border border-slate-200 bg-white p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="font-bold text-slate-800">{title}</div>
        <div className="rounded-[7px] bg-slate-100 px-2 py-1 text-[12px] font-bold text-slate-700">{remainingText}</div>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full ${barColor}`} style={{ width: `${remaining}%` }} />
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
          <div className="min-w-0 whitespace-pre-line break-words font-medium text-slate-800">{value}</div>
        </div>
      ))}
    </div>
  );
}

function PathRow({
  label,
  path,
  t,
  onOpenPath,
}: {
  label: string;
  path: string;
  t: (text: string) => string;
  onOpenPath: (path: string) => void;
}) {
  const copyPath = async () => {
    await navigator.clipboard.writeText(path);
    message.success(t("路径已复制"));
  };
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)_auto] items-center gap-3 rounded-[9px] border border-slate-200 bg-white px-4 py-3 max-[720px]:grid-cols-1">
      <div className="text-sm font-bold text-slate-600">{label}</div>
      <Tooltip title={path}>
        <div className="min-w-0 truncate font-mono text-xs text-slate-500">{path}</div>
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
  t: (text: string) => string,
) {
  if (profile.running) {
    return t("关闭");
  }

  return runningCount > 0 ? t("切换") : t("启动");
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

  const hasValue = window?.remainingPercent !== null && window?.remainingPercent !== undefined;
  const percent = clampPercent(window?.remainingPercent);
  let barColor = hasValue ? "bg-emerald-500" : "bg-slate-300";
  if (hasValue && percent <= 20) barColor = "bg-red-500";
  else if (hasValue && percent <= 50) barColor = "bg-amber-500";

  return (
    <Tooltip
      title={language === "en-US"
        ? `Used ${usedText}, remaining ${remainingText}, resets ${countdownText} (${resetText})`
        : `已用 ${usedText}，剩余 ${remainingText}，${countdownText}重置（${resetText}）`}
    >
      <span className="grid min-w-0 gap-1.5">
        <span className="flex items-center justify-between gap-1 text-[11.5px] leading-none text-slate-500">
          <span className="shrink-0 whitespace-nowrap font-medium">{label}</span>
          <strong className="shrink-0 text-[13px] font-bold text-gray-900 tabular-nums">
            {remainingText}
          </strong>
        </span>
        <span
          className="block h-1.5 overflow-hidden rounded-full bg-slate-100 ring-1 ring-inset ring-slate-200/60"
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
  return profiles
    .filter(isRecommendableProfile)
    .sort(compareRecommendedProfiles)[0]?.name ?? "";
}

function compareRecommendedProfiles(left: ProfileSummary, right: ProfileSummary) {
  const tierDifference = recommendationTier(left) - recommendationTier(right);
  if (tierDifference !== 0) return tierDifference;

  if (isRecommendableProfile(left) && isRecommendableProfile(right)) {
    const usageDifference = usageScore(right.usage) - usageScore(left.usage);
    if (usageDifference !== 0) return usageDifference;
  }

  if (left.running !== right.running) return left.running ? -1 : 1;
  return left.name.localeCompare(right.name);
}

function recommendationTier(profile: ProfileSummary) {
  if (isRecommendableProfile(profile)) return 0;
  return isHealthyProfile(profile) ? 1 : 2;
}

function isRecommendableProfile(profile: ProfileSummary) {
  return isHealthyProfile(profile)
    && Boolean(profile.usage?.oneWeek)
    && !profile.usage?.error
    && !profile.usage?.spendControlReached
    && !profile.usage?.rateLimitReachedType;
}

function usageScore(usage: ProfileUsage | null) {
  if (!usage) {
    return -1;
  }
  return usage.oneWeek?.remainingPercent ?? 0;
}

function ResetCreditSummary({
  usage,
  language,
  compact = false,
  onUseCredit,
  disabled,
  resetPending,
}: {
  usage: ProfileUsage | null;
  language: "zh-CN" | "en-US";
  compact?: boolean;
  onUseCredit?: (credit: ResetCredit | null) => void;
  disabled?: boolean;
  resetPending?: boolean;
}) {
  const { t } = useI18n();
  const count = usage?.resetCredits;
  const cards = usage?.resetCreditItems ?? [];
  const countText = count == null ? "-" : language === "en-US" ? `${count} available` : `${count} 次可用`;

  if (compact) {
    return (
      <div className="flex min-w-0 items-center justify-between gap-2 border-t border-slate-100 pt-2 text-[11.5px]">
        <span className="flex shrink-0 items-center gap-1.5 font-medium text-slate-500">
          <RefreshCw size={11} aria-hidden />
          {language === "en-US" ? "Resets" : "刷新次数"}
        </span>
        <strong className={count ? "font-bold text-brand-700 tabular-nums" : "font-bold text-slate-600 tabular-nums"}>{count == null ? "-" : count}</strong>
      </div>
    );
  }

  const canUseCredit = Boolean(onUseCredit && usage?.resetAccountScope && (count ?? 0) > 0 && !resetPending);
  const rows = cards.length
    ? cards.map((card) => ({ key: card.id, expiresAt: card.expiresAt, card }))
    : (usage?.resetCreditExpiresAt ?? []).map((expiresAt, index) => ({ key: `expiry-${index}`, expiresAt, card: null }));

  return (
    <section className="overflow-hidden rounded-[9px] border border-brand-100 bg-brand-50/55">
      <div className="flex items-center justify-between gap-3 px-3.5 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-[8px] bg-white text-brand-600 shadow-[0_2px_8px_rgba(13,148,136,0.09)]">
            <RefreshCw size={15} aria-hidden />
          </span>
          <div className="min-w-0">
            <div className="text-[11.5px] font-semibold text-slate-500">{language === "en-US" ? "Available resets" : "可刷新次数"}</div>
            <div className="mt-0.5 text-[12px] text-slate-600">{language === "en-US" ? "Expiration dates" : "刷新次数过期时间"}</div>
          </div>
        </div>
        <strong className="shrink-0 text-[22px] font-bold tracking-[-0.04em] text-brand-700 tabular-nums">{countText}</strong>
      </div>
      <div className="grid gap-1 border-t border-brand-100/80 bg-white/60 px-3.5 py-2 text-[11px] text-slate-500">
        {rows.map(({ key, expiresAt, card }, index) => (
          <div key={key} className="flex min-w-0 items-center justify-between gap-2">
            <span>
              <span className="mr-2 font-semibold text-slate-400">#{index + 1}</span>
              {expiresAt == null ? t("无到期时间") : formatTimestamp(expiresAt, language)}
            </span>
            {card && canUseCredit ? (
              <Button
                size="small"
                color="primary"
                variant="text"
                icon={<ChevronRight size={13} aria-hidden />}
                iconPosition="end"
                autoInsertSpace={false}
                className="shrink-0 !gap-1 !px-2 !text-xs !font-medium enabled:!text-teal-700 enabled:hover:!bg-brand-50"
                disabled={disabled || (expiresAt != null && expiresAt <= Date.now() / 1000)}
                onClick={() => onUseCredit?.(card)}
              >
                {t("使用")}
              </Button>
            ) : null}
          </div>
        ))}
        {resetPending ? (
          <Button size="small" className="justify-self-start" disabled={disabled} onClick={() => onUseCredit?.(null)}>{t("重试重置额度")}</Button>
        ) : canUseCredit && !cards.length ? (
          <Button size="small" className="justify-self-start" disabled={disabled} onClick={() => onUseCredit?.(null)}>{t("使用 1 次")}</Button>
        ) : !rows.length ? <div className="text-slate-400">{t("未返回过期时间")}</div> : null}
      </div>
    </section>
  );
}

function formatCreditExpiries(values: number[] | null | undefined, language: "zh-CN" | "en-US") {
  if (!values?.length) {
    return "-";
  }
  return values.map((value, index) => `${index + 1}. ${formatTimestamp(value, language)}`).join("\n");
}
