import { useEffect, useState } from "react";
import { Alert, Button, Input, Space, Spin, Tooltip, message } from "antd";
import { RefreshCw, Save } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import type { TomlConfigState } from "../types";

const { TextArea } = Input;

export function TomlConfigPage() {
  const [state, setState] = useState<TomlConfigState | null>(null);
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const refresh = async () => {
    setLoading(true);
    try {
      const next = await invokeLauncher<TomlConfigState>("read_toml_config");
      setState(next);
      setContent(next.content);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "读取 TOML 配置失败");
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
      message.success(next.backupPath ? "已保存，旧配置已备份" : "已保存");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "保存 TOML 配置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="flex items-center justify-between gap-3 rounded-panel border border-shell-line bg-white px-5 py-4 shadow-[0_10px_28px_rgba(15,23,42,0.045)] max-[960px]:items-start max-[960px]:flex-col">
        <div className="min-w-0">
          <div className="text-base font-bold text-slate-800">当前 config.toml</div>
          <Tooltip title={state?.path}>
            <div className="mt-1 truncate text-xs text-slate-500">
              {state?.path || "读取中"}
            </div>
          </Tooltip>
        </div>
        <Space wrap>
          <Button icon={<RefreshCw size={15} />} loading={loading} onClick={refresh}>
            刷新
          </Button>
          <Button type="primary" icon={<Save size={15} />} loading={saving} onClick={save}>
            保存
          </Button>
        </Space>
      </div>

      {state && !state.exists ? (
        <Alert
          type="warning"
          showIcon
          message="当前 config.toml 不存在，保存后会自动创建。"
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
          <div className="truncate text-xs text-slate-500">最近备份：{state.backupPath}</div>
        </Tooltip>
      ) : null}
    </div>
  );
}
