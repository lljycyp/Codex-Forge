import { useEffect, useState } from "react";
import { Alert, Button, Input, Modal, Select, Spin, Tooltip, message } from "antd";
import { GitCompare, Save } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";
import type { AppState, ProfileSummary, TomlConfigState } from "../types";

const { TextArea } = Input;
const SYSTEM_PROFILE_NAME = "__system__";
const isMulti = (mode: AppState["launchMode"]) => mode === "multi";

type TomlConfigPageProps = {
  appState: AppState;
  profiles: ProfileSummary[];
};

export function TomlConfigPage({ appState, profiles }: TomlConfigPageProps) {
  const { t } = useI18n();
  const [state, setState] = useState<TomlConfigState | null>(null);
  const [content, setContent] = useState("");
  const [profileName, setProfileName] = useState(appState.activeProfile || profiles[0]?.name || SYSTEM_PROFILE_NAME);
  const [syncOpen, setSyncOpen] = useState(false);
  const [syncTargetProfile, setSyncTargetProfile] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [compareTarget, setCompareTarget] = useState(SYSTEM_PROFILE_NAME);
  const [compareDiff, setCompareDiff] = useState("");
  const [compareKeys, setCompareKeys] = useState<string[]>([]);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);

  const multiMode = isMulti(appState.launchMode);
  const noProfile = multiMode && !profileName;
  const targetPayload = multiMode ? { profileName } : {};
  const profileOptions = [
    { label: t("系统级配置"), value: SYSTEM_PROFILE_NAME },
    ...profiles.map((profile) => ({ label: profile.name, value: profile.name })),
  ];
  const accountOptions = profiles.map((profile) => ({ label: profile.name, value: profile.name }));

  useEffect(() => {
    if (multiMode && !profileName) {
      setProfileName(appState.activeProfile || profiles[0]?.name || SYSTEM_PROFILE_NAME);
    }
  }, [appState.activeProfile, multiMode, profileName, profiles]);

  const refresh = async () => {
    if (noProfile) {
      setState(null);
      setContent("");
      return;
    }
    setLoading(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("read_toml_config", targetPayload);
      setState(next);
      setContent(next.content);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("读取 TOML 配置失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [profileName, multiMode]);

  const save = async () => {
    setSaving(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("save_toml_config", { ...targetPayload, content });
      setState(next);
      setContent(next.content);
      message.success(next.backupPath ? t("已保存，旧配置已备份") : t("已保存"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("保存 TOML 配置失败"));
    } finally {
      setSaving(false);
    }
  };

  const syncAll = async () => {
    setSaving(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("save_toml_config", { content, scope: "all" });
      setState(next);
      message.success(t("已同步到所有账号"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("同步 TOML 配置失败"));
    } finally {
      setSaving(false);
    }
  };

  const syncToProfile = async () => {
    if (!syncTargetProfile) {
      return;
    }
    setSaving(true);
    try {
      await invokeLauncher<TomlConfigState>("save_toml_config", { content, profileName: syncTargetProfile });
      message.success(t("已复制到指定账号"));
      setSyncOpen(false);
      setSyncTargetProfile("");
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("同步 TOML 配置失败"));
    } finally {
      setSaving(false);
    }
  };

  const compareConfig = async () => {
    setLoading(true);
    try {
      const result = await invokeLauncher<{ identical: boolean; diff: string; sourceKeys: string[] }>("compare_toml_configs", {
        sourceProfile: profileName,
        targetProfile: compareTarget,
      });
      setCompareDiff(result.identical ? t("两份配置完全一致") : result.diff);
      setCompareKeys(result.sourceKeys);
      setSelectedKeys([]);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("比较 TOML 配置失败"));
    } finally {
      setLoading(false);
    }
  };

  const syncSelectedKeys = async () => {
    setSaving(true);
    try {
      await invokeLauncher("sync_toml_keys", {
        sourceProfile: profileName,
        targetProfile: compareTarget,
        keys: selectedKeys,
      });
      message.success(t("已同步选中的配置项"));
      await compareConfig();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("同步配置项失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-panel border border-shell-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
        <div className="min-w-[260px] flex-1">
          <div className="flex flex-wrap items-center gap-2 text-base font-bold text-slate-800">
            {t("当前 config.toml")}
            {multiMode ? (
              <span className="rounded-[6px] border border-brand-100 bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-600">
                {t("多开")}
              </span>
            ) : null}
          </div>
          <Tooltip title={state?.path}>
            <div className="mt-1 truncate text-xs text-slate-500">
              {noProfile ? t("请选择账号后查看配置") : state?.path || t("读取中")}
            </div>
          </Tooltip>
        </div>
        <div className="flex max-w-full flex-wrap items-center justify-end gap-2 max-[960px]:w-full max-[960px]:justify-start">
          {multiMode ? (
            <Select
              className="w-[292px] max-w-full"
              value={profileName || undefined}
              placeholder={t("选择账号")}
              options={profileOptions}
              onChange={setProfileName}
            />
          ) : null}
          <Button type="primary" icon={<Save size={15} />} loading={saving} disabled={noProfile} onClick={save}>
            {t("保存")}
          </Button>
          {multiMode ? (
            <Button
              icon={<GitCompare size={15} />}
              disabled={noProfile}
              onClick={() => {
                setCompareTarget(profileName === SYSTEM_PROFILE_NAME ? profiles[0]?.name || SYSTEM_PROFILE_NAME : SYSTEM_PROFILE_NAME);
                setCompareDiff("");
                setCompareKeys([]);
                setSelectedKeys([]);
                setCompareOpen(true);
              }}
            >
              {t("配置对比")}
            </Button>
          ) : null}
          {multiMode ? (
            <Button loading={saving} disabled={noProfile} onClick={syncAll}>
              {t("同步全部账号")}
            </Button>
          ) : null}
          {multiMode ? (
            <Button
              loading={saving}
              disabled={noProfile || profiles.length === 0}
              onClick={() => {
                setSyncTargetProfile(profiles[0]?.name || "");
                setSyncOpen(true);
              }}
            >
              {t("同步到账号")}
            </Button>
          ) : null}
        </div>
      </div>

      {state && !state.exists ? (
        <Alert
          type="warning"
          showIcon
          message={t("当前 config.toml 不存在，保存后会自动创建。")}
        />
      ) : null}

      <div className="min-h-0 flex-1 overflow-hidden rounded-panel border border-shell-line bg-white shadow-[0_10px_28px_rgba(15,23,42,0.045)]">
        {loading && !state ? (
          <div className="flex h-full min-h-0 items-center justify-center">
            <Spin />
          </div>
        ) : noProfile ? (
          <div className="flex h-full min-h-0 items-center justify-center text-sm text-slate-500">
            {t("请选择账号后查看配置")}
          </div>
        ) : (
          <TextArea
            className="!h-full !min-h-0 !resize-none !overflow-auto !rounded-none !border-0 !p-5 !font-mono !text-[13px] !leading-6"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder={'model = "gpt-5-codex"'}
            spellCheck={false}
          />
        )}
      </div>

      {state?.backupPath ? (
        <Tooltip title={state.backupPath}>
          <div className="truncate text-xs text-slate-500">{t("最近备份：")}{state.backupPath}</div>
        </Tooltip>
      ) : null}
      <Modal
        title={t("同步到账号")}
        open={syncOpen}
        onCancel={() => {
          setSyncOpen(false);
          setSyncTargetProfile("");
        }}
        onOk={syncToProfile}
        okText={t("同步")}
        cancelText={t("取消")}
        okButtonProps={{ disabled: !syncTargetProfile }}
      >
        <Select
          className="w-full"
          value={syncTargetProfile || undefined}
          placeholder={t("选择目标账号")}
          options={accountOptions}
          onChange={setSyncTargetProfile}
        />
      </Modal>
      <Modal
        width={860}
        title={t("配置差异对比")}
        open={compareOpen}
        onCancel={() => setCompareOpen(false)}
        footer={<Button onClick={() => setCompareOpen(false)}>{t("关闭")}</Button>}
      >
        <div className="mb-3 flex items-center gap-2">
          <Select
            className="min-w-[280px]"
            value={compareTarget}
            options={profileOptions.filter((option) => option.value !== profileName)}
            onChange={(value) => {
              setCompareTarget(value);
              setCompareDiff("");
            }}
          />
          <Button type="primary" loading={loading} onClick={compareConfig}>{t("开始比较")}</Button>
        </div>
        <div className="mb-3 flex items-center gap-2">
          <Select
            mode="multiple"
            className="min-w-0 flex-1"
            value={selectedKeys}
            options={compareKeys.map((key) => ({ label: key, value: key }))}
            placeholder={t("选择要从当前配置同步到目标配置的顶层配置项")}
            onChange={setSelectedKeys}
          />
          <Button disabled={selectedKeys.length === 0} loading={saving} onClick={syncSelectedKeys}>{t("同步选中项")}</Button>
        </div>
        <TextArea
          className="!h-[480px] !font-mono !text-xs"
          value={compareDiff}
          readOnly
          placeholder={t("选择目标配置后开始比较")}
        />
      </Modal>
    </div>
  );
}
