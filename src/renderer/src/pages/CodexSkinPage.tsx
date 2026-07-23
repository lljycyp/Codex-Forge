import { Palette } from "lucide-react";
import { CodexSkinSettings } from "../components/CodexSkinSettings";
import { useI18n } from "../i18n";
import type { AppState, RunCommand } from "../types";

type CodexSkinPageProps = {
  appState: AppState;
  runCommand: RunCommand;
};

export function CodexSkinPage({ appState, runCommand }: CodexSkinPageProps) {
  const { t } = useI18n();

  return (
    <div className="mx-auto w-full max-w-[960px] pb-8">
      <div className="mb-5 flex items-center gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700">
          <Palette size={20} />
        </div>
        <div>
          <h1 className="m-0 text-xl font-bold text-slate-900">{t("Codex 换肤")}</h1>
          <p className="m-0 mt-1 text-sm text-slate-500">
            {t("导入并切换 Codex 背景图片")}
          </p>
        </div>
      </div>
      <section className="rounded-xl border border-slate-200 bg-slate-50/60 p-5">
        <CodexSkinSettings appState={appState} runCommand={runCommand} />
      </section>
    </div>
  );
}
