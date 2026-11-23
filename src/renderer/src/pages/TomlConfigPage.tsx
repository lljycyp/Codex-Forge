import { useEffect, useState } from "react";
import { Alert, Button, Input, Spin, Tooltip, message } from "antd";
import { Save } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";
import type { TomlConfigState } from "../types";

const { TextArea } = Input;
type TomlConfigPageProps = {
  onDirtyChange: (dirty: boolean) => void;
};

export function TomlConfigPage({ onDirtyChange }: TomlConfigPageProps) {
  const { t } = useI18n();
  const [state, setState] = useState<TomlConfigState | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const dirty = state !== null && content !== state.content;

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  const refresh = async () => {
    setLoading(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("read_toml_config");
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
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("save_toml_config", { content });
      setState(next);
      setContent(next.content);
      message.success(next.backupPath ? t("已保存，旧配置已备份") : t("已保存"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("保存 TOML 配置失败"));
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
          </div>
          <Tooltip title={state?.path}>
            <div className="mt-1 truncate text-xs text-slate-500">
              {state?.path || t("读取中")}
            </div>
          </Tooltip>
        </div>
        <div className="flex max-w-full flex-wrap items-center justify-end gap-2 max-[960px]:w-full max-[960px]:justify-start">
          <Button type="primary" icon={<Save size={15} />} loading={saving} onClick={save}>
            {t("保存")}
          </Button>
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
    </div>
  );
}
