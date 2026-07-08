import { Button, Tooltip } from "antd";
import { CheckCircle2, Folder, Settings2 } from "lucide-react";
import { Metric } from "../components/Metric";
import { useI18n } from "../i18n";
import type { ReactNode } from "react";
import type { AppState, ProfileSummary } from "../types";

type HomePageProps = {
  appState: AppState;
  profiles: ProfileSummary[];
  onOpenProfiles: () => void;
};

const sectionClass =
  "rounded-card border border-shell-line bg-white p-5 shadow-[0_10px_28px_rgba(15,23,42,0.045)]";

const statusPillClass =
  "inline-flex h-[22px] items-center rounded-[6px] border px-2 text-[11.5px] font-bold leading-none";

export function HomePage({ appState, profiles, onOpenProfiles }: HomePageProps) {
  const { t } = useI18n();
  const healthyCount = profiles.filter(isHealthyProfile).length;
  const abnormalCount = profiles.length - healthyCount;
  const recentProfiles = profiles.slice(0, 4);

  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-4 gap-3 max-[1120px]:grid-cols-2 max-[720px]:grid-cols-1">
        <Metric title={t("账号总数")} value={profiles.length || appState.profileCount} note={t("已保存账号")} />
        <Metric title={t("运行中")} value={appState.runningCount} note={t("当前 Codex 实例")} statusText={appState.runningCount > 0 ? t("活跃") : t("空闲")} />
        <Metric title={t("健康账号")} value={healthyCount} note={t("资料目录和认证文件正常")} statusText={t("正常")} />
        <Metric
          title={t("异常账号")}
          value={abnormalCount}
          note={t("缺少目录或 auth.json")}
          statusText={abnormalCount > 0 ? t("需处理") : t("正常")}
          statusTone={abnormalCount > 0 ? "amber" : "green"}
        />
      </div>

      <div className="grid grid-cols-2 gap-4 max-[960px]:grid-cols-1">
        <section className={sectionClass}>
          <SectionTitle icon={<Settings2 size={16} />} title={t("当前模式")} />
          <div className="mt-4 grid gap-3">
            <InfoRow label={t("启动模式")} value={formatLaunchMode(appState.launchMode, t)} />
            <InfoRow label={t("配置模式")} value={appState.launchMode === "multi" ? t("账号 CodexHome 配置") : t("系统配置")} />
            <InfoRow label={t("当前账号")} value={appState.activeProfile || t("未选择")} />
            <InfoRow label={t("Codex 命令")} value={appState.codexCommandAvailable ? t("可用") : t("不可用")} tone={appState.codexCommandAvailable ? "green" : "amber"} />
          </div>
        </section>

        <section className={sectionClass}>
          <SectionTitle icon={<Folder size={16} />} title={t("当前设置")} />
          <div className="mt-4 grid gap-3">
            <PathRow label={t("账号资料根目录")} value={appState.profileRoot || t("未设置")} ok={appState.profileRootExists} />
            <PathRow label="auth.json" value={appState.activeAuthPath || t("未找到")} ok={appState.activeAuthExists} />
            <PathRow label="config.toml" value={appState.activeConfigPath || t("未找到")} ok={appState.activeConfigExists} />
          </div>
        </section>
      </div>

      <section className={sectionClass}>
        <div className="flex items-center justify-between gap-4 border-b border-[#ecf1f6] pb-4">
          <SectionTitle icon={<CheckCircle2 size={16} />} title={t("账号状态")} />
          <Button type="primary" onClick={onOpenProfiles}>
            {t("查看全部账号")}
          </Button>
        </div>

        {recentProfiles.length ? (
          <div className="divide-y divide-[#ecf1f6]">
            {recentProfiles.map((profile) => (
              <div key={profile.name} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 py-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="truncate text-sm font-bold text-gray-900">{profile.name}</span>
                    {profile.active ? <StatusPill tone="blue" text={t("当前账号")} /> : null}
                    <StatusPill tone={profile.running ? "green" : "slate"} text={profile.running ? t("运行中") : t("就绪")} />
                    {!profile.authExists ? <StatusPill tone="amber" text={t("认证缺失")} /> : null}
                  </div>
                  <Tooltip title={profile.profileDir} placement="topLeft">
                    <div className="mt-1 truncate font-mono text-xs text-slate-400">
                      {profile.profileDir}
                    </div>
                  </Tooltip>
                </div>
                <span className="text-xs font-semibold text-slate-500">
                  {formatPlanType(profile.usage?.planType, t)}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex min-h-[150px] items-center justify-center text-sm text-slate-400">
            {t("暂无账号")}
          </div>
        )}
      </section>
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="grid h-7 w-7 place-items-center rounded-[7px] bg-brand-50 text-brand-600">
        {icon}
      </span>
      <h2 className="m-0 text-base font-extrabold leading-none text-slate-800">{title}</h2>
    </div>
  );
}

function InfoRow({ label, value, tone = "slate" }: { label: string; value: string; tone?: "green" | "amber" | "slate" }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-[8px] bg-slate-50 px-3 py-2.5">
      <span className="text-sm font-semibold text-slate-500">{label}</span>
      <StatusPill tone={tone} text={value} />
    </div>
  );
}

function PathRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  const { t } = useI18n();
  return (
    <div className="grid gap-1 rounded-[8px] bg-slate-50 px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-slate-500">{label}</span>
        <StatusPill tone={ok ? "green" : "amber"} text={ok ? t("存在") : t("缺失")} />
      </div>
      <Tooltip title={value} placement="topLeft">
        <div className="truncate font-mono text-xs text-slate-400">{value}</div>
      </Tooltip>
    </div>
  );
}

function StatusPill({ tone, text }: { tone: "green" | "amber" | "blue" | "slate"; text: string }) {
  const toneClass =
    tone === "green"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : tone === "amber"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : tone === "blue"
          ? "border-blue-200 bg-blue-50 text-blue-700"
          : "border-slate-200 bg-slate-50 text-slate-500";

  return <span className={`${statusPillClass} ${toneClass}`}>{text}</span>;
}

function isHealthyProfile(profile: ProfileSummary) {
  return profile.profileDirExists && profile.authExists;
}

function formatLaunchMode(mode: AppState["launchMode"], t: (text: string) => string) {
  return mode === "multi" ? t("多开隔离模式") : t("账号切换模式");
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
