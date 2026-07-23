import { useEffect, useState } from "react";
import { Alert, Button, Popconfirm, Switch, message } from "antd";
import { ImagePlus, Palette, Pause, Play, Trash2 } from "lucide-react";
import { useI18n } from "../i18n";
import type { AppState, CodexSkinThemeState, RunCommand } from "../types";

const emptyThemeState: CodexSkinThemeState = {
  activeThemeId: "builtin-aurora",
  paused: false,
  themes: [{
    id: "builtin-aurora",
    name: "Forge Aurora",
    builtIn: true,
    previewDataUrl: "",
    focusX: 50,
    focusY: 50,
    safeArea: "left",
    appearance: "auto",
  }],
};

type CodexSkinSettingsProps = {
  appState: AppState;
  runCommand: RunCommand;
};

export function CodexSkinSettings({ appState, runCommand }: CodexSkinSettingsProps) {
  const { t } = useI18n();
  const [themeState, setThemeState] = useState<CodexSkinThemeState>(emptyThemeState);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let disposed = false;
    void window.launcherApi.getCodexSkinState?.()
      .then((state) => {
        if (!disposed) {
          setThemeState(state);
          setLoadError("");
        }
      })
      .catch((error) => {
        if (!disposed) setLoadError(error instanceof Error ? error.message : t("读取主题失败"));
      });
    return () => {
      disposed = true;
    };
  }, [t]);

  const changeEnabled = async (enabled: boolean) => {
    setLoading(true);
    try {
      await runCommand(
        "set_codex_skin_enabled",
        { enabled },
        enabled ? t("已开启 Codex 皮肤") : t("已恢复 Codex 官方外观"),
        { blocking: false },
      );
    } finally {
      setLoading(false);
    }
  };

  const importTheme = async () => {
    if (!window.launcherApi.importCodexSkinTheme) return;
    setLoading(true);
    try {
      const previousIds = new Set(themeState.themes.map((theme) => theme.id));
      const state = await window.launcherApi.importCodexSkinTheme();
      setThemeState(state);
      if (state.themes.some((theme) => !previousIds.has(theme.id))) {
        message.success(t("主题已导入并应用"));
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("导入主题失败"));
    } finally {
      setLoading(false);
    }
  };

  const selectTheme = async (themeId: string) => {
    if (!window.launcherApi.setActiveCodexSkinTheme || themeId === themeState.activeThemeId) return;
    setLoading(true);
    try {
      setThemeState(await window.launcherApi.setActiveCodexSkinTheme(themeId));
      message.success(t("主题已切换"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("切换主题失败"));
    } finally {
      setLoading(false);
    }
  };

  const deleteTheme = async (themeId: string) => {
    if (!window.launcherApi.deleteCodexSkinTheme) return;
    setLoading(true);
    try {
      setThemeState(await window.launcherApi.deleteCodexSkinTheme(themeId));
      message.success(t("主题已删除"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("删除主题失败"));
    } finally {
      setLoading(false);
    }
  };

  const changePaused = async () => {
    if (!window.launcherApi.setCodexSkinPaused) return;
    setLoading(true);
    try {
      const state = await window.launcherApi.setCodexSkinPaused(!themeState.paused);
      setThemeState(state);
      message.success(state.paused ? t("皮肤已暂停") : t("皮肤已恢复"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("切换皮肤状态失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 font-semibold text-slate-700">
            <Palette size={16} />
            {t("Codex 皮肤")}
          </div>
          <div className="mt-1 text-sm leading-6 text-slate-500">
            {t("支持账号切换与多开隔离模式；切换开关时会安全重启正在运行的 Codex。")}
          </div>
        </div>
        <Switch
          aria-label={t("Codex 皮肤")}
          checked={appState.codexSkinEnabled}
          loading={loading}
          onChange={(value) => void changeEnabled(value)}
        />
      </div>

      {loadError ? <Alert className="mt-4" type="error" showIcon message={loadError} /> : null}

      <div className="mt-4 rounded-xl border border-slate-200 bg-white/80 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-semibold text-slate-700">{t("本地主题")}</div>
            <div className="mt-1 text-xs leading-5 text-slate-500">
              {t("图片保存在本机 Forge 数据目录，不会上传。")}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              icon={<ImagePlus size={15} />}
              loading={loading}
              onClick={() => void importTheme()}
            >
              {t("导入背景图")}
            </Button>
            <Button
              icon={themeState.paused ? <Play size={15} /> : <Pause size={15} />}
              disabled={!appState.codexSkinEnabled}
              loading={loading}
              onClick={() => void changePaused()}
            >
              {themeState.paused ? t("继续显示") : t("暂停显示")}
            </Button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {themeState.themes.map((theme) => {
            const active = theme.id === themeState.activeThemeId;
            return (
              <div
                key={theme.id}
                className={`relative overflow-hidden rounded-lg border p-2 transition-colors ${
                  active ? "border-brand-600 bg-brand-50" : "border-slate-200 bg-white hover:border-slate-300"
                }`}
              >
                <button
                  type="button"
                  aria-pressed={active}
                  aria-label={`${t("切换主题")}：${theme.name}`}
                  className="block w-full appearance-none border-0 bg-transparent p-0 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600"
                  disabled={loading}
                  onClick={() => void selectTheme(theme.id)}
                >
                  <div
                    className="h-24 w-full rounded-md bg-[radial-gradient(circle_at_80%_20%,rgba(45,212,191,.45),transparent_34%),linear-gradient(135deg,#07151e,#14334a)] bg-cover bg-center"
                    style={theme.previewDataUrl ? { backgroundImage: `url(${theme.previewDataUrl})` } : undefined}
                  />
                  <div className="mt-2 flex items-center justify-between gap-2 px-1">
                    <span className="truncate text-sm font-semibold text-slate-700">{theme.name}</span>
                    {active ? <span className="text-xs font-semibold text-brand-700">{t("当前")}</span> : null}
                  </div>
                </button>
                {!theme.builtIn ? (
                  <Popconfirm
                    title={t("删除这个本地主题？")}
                    okText={t("删除")}
                    cancelText={t("取消")}
                    onConfirm={() => void deleteTheme(theme.id)}
                  >
                    <Button
                      type="text"
                      danger
                      size="small"
                      aria-label={`${t("删除主题")}：${theme.name}`}
                      className="absolute right-2 top-2 bg-white/85"
                      icon={<Trash2 size={14} />}
                    />
                  </Popconfirm>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
