import { useEffect, useState } from "react";
import { Alert, Button, Input, Space, Switch, Tag, message } from "antd";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";

type GatewayStatus = {
  enabled: boolean;
  running: boolean;
  baseUrl?: string;
  activeRequests: number;
  maxConcurrentPerAccount?: number;
  error?: string;
  accounts: { id: string; name: string; active: number; reason: string }[];
  recentRequests: { account: string; model: string; status: number; outcome: string; seconds: number; at: number }[];
};

export function LoadBalancerSettings({ privacyMode }: { privacyMode: boolean }) {
  const { language } = useI18n();
  const en = language === "en-US";
  const [status, setStatus] = useState<GatewayStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [launching, setLaunching] = useState(false);

  const launchClient = async () => {
    setLaunching(true);
    setError("");
    try {
      const result = await invokeLauncher<{ alreadyRunning: boolean }>("launch_load_balancer_client");
      message.success(result.alreadyRunning
        ? (en ? "The dedicated client is already open" : "独立客户端已打开")
        : (en ? "Dedicated client launched; waiting for its first request" : "已启动独立客户端，等待首个请求验证接入"));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setLaunching(false);
    }
  };

  useEffect(() => {
    if (busy) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await invokeLauncher<GatewayStatus>("get_load_balancer_status");
        if (!disposed) { setStatus(next); setPollError(""); }
      } catch (failure) {
        if (!disposed) setPollError(failure instanceof Error ? failure.message : String(failure));
      } finally {
        if (!disposed) timer = setTimeout(() => void poll(), 3000);
      }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); };
  }, [busy]);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    setError("");
    try {
      setStatus(await invokeLauncher<GatewayStatus>("set_load_balancer_enabled", { enabled }));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  const copy = async (kind: "key" | "config") => {
    try {
      const text = kind === "key"
        ? (await invokeLauncher<{ key: string }>("get_load_balancer_key")).key
        : `model_provider = "forge"\n\n[model_providers.forge]\nname = "Forge"\nbase_url = "${status?.baseUrl}"\nenv_key = "FORGE_GATEWAY_KEY"\nwire_api = "responses"\nrequires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n`;
      await navigator.clipboard.writeText(text);
      message.success(en ? "Copied" : "已复制");
    } catch (failure) {
      message.error(failure instanceof Error ? failure.message : String(failure));
    }
  };

  return (
    <div className="mt-8 rounded-xl border border-[#e4ebf3] bg-slate-50/50 p-6">
      <div className="flex items-center justify-between gap-6">
        <div>
          <div className="font-semibold text-slate-700">
            {en ? "Account load balancing" : "账号负载均衡"}
            <Tag className="ml-2">{en ? "Experimental" : "实验功能"}</Tag>
          </div>
          <div className="mt-1 text-sm leading-6 text-slate-500">
            {en ? "Use existing accounts. Each model request goes to the least busy available account; conversations are not pinned." : "复用现有账号，每次模型请求分配给当前负载最低的可用账号，会话不固定账号。"}
          </div>
        </div>
        <Switch aria-label={en ? "Enable account load balancing" : "启用账号负载均衡"}
          checked={status?.enabled ?? false} disabled={!status || launching} loading={busy}
          onChange={(enabled) => void toggle(enabled)} />
      </div>
      <div className="mt-3 text-sm leading-6 text-slate-500">
        {en ? "Off by default. This switch controls the local gateway only; it does not change Codex configuration, login, or running processes. Exiting Forge stops the gateway. Switching off stops new requests while active requests finish." : "默认关闭。开关仅控制本地网关，不修改 Codex 配置、登录或运行中的进程。退出 Forge 会停止网关；关闭开关后停止接收新请求，已有请求继续结束。"}
      </div>
      {(error || pollError || status?.error) && <Alert className="mt-3" type="error" showIcon message={error || pollError || status?.error} />}
      {status?.enabled && (
        <div className="mt-4 grid gap-3">
          <div className="flex items-center gap-3 text-sm">
            <Tag color={status.running ? "green" : "red"}>{status.running ? (en ? "Running" : "运行中") : (en ? "Stopped" : "已停止")}</Tag>
            <span>{en ? "Active requests" : "正在处理"}: {status.activeRequests}</span>
            <span>{en ? "Per-account concurrency" : "每账号并发上限"}: {status.maxConcurrentPerAccount ?? 2}</span>
          </div>
          <Input aria-label="Base URL" readOnly value={status.baseUrl || ""} addonBefore="Base URL" />
          <Space wrap>
            <Button type="primary" disabled={!status.running || busy} loading={launching} onClick={() => void launchClient()}>{en ? "Launch dedicated client" : "启动负载均衡客户端"}</Button>
            <Button disabled={!status.running} onClick={() => void copy("key")}>{en ? "Copy Key" : "复制 Key"}</Button>
            <Button disabled={!status.running} onClick={() => void copy("config")}>{en ? "Copy config snippet" : "复制配置片段"}</Button>
          </Space>
          <div className="text-sm leading-6 text-slate-500">
            {en ? "Launch creates a separate client with its own settings and history, and passes the gateway Key automatically. Your current client is unchanged." : "启动按钮会自动配置地址和 Key，使用独立的设置及会话目录，不影响当前客户端。"}
            {status.recentRequests.some((request) => request.outcome === "completed")
              ? (en ? " A request has completed successfully." : " 已有请求成功完成。")
              : (en ? " No successful requests yet; running means only the gateway is ready." : " 尚无成功请求；运行中仅表示网关已就绪。")}
          </div>
          <div className="text-sm leading-6 text-slate-500">
            {en ? "Merge the snippet into your chosen Codex config and set FORGE_GATEWAY_KEY in that client's environment to the copied Key. The Key authenticates only to Forge. Configure the desired model separately. Apply to a separate test client first." : "将片段合并到目标 Codex 配置，并在该客户端的环境变量 FORGE_GATEWAY_KEY 中填入复制的 Key。Key 仅用于访问 Forge，模型沿用你的设置。建议先接入独立测试客户端。"}
          </div>
          <Alert type="warning" showIcon
            message={en ? "Full-history HTTP requests only" : "仅支持携带完整历史的 HTTP 请求"}
            description={en ? "Tool results and encrypted reasoning are forwarded unchanged. Client-side text compaction is supported. No WebSocket, server-side continuation, file IDs or server-side compaction blocks. Full accounts return an error rather than queueing. Failed requests are not replayed. Tokens are read only; refresh quota or sign in again when they expire. Subscription account rotation may violate usage restrictions and risk account suspension." : "工具结果和加密推理原样转发，支持客户端文本压缩。暂不支持 WebSocket、服务端续接、文件 ID 及服务端压缩块。满载时返回错误，不排队；失败请求不自动重放。只读取现有令牌，过期后需刷新额度或重新授权。订阅账号轮换可能涉及使用限制，并存在账号停用风险。"} />
          {status.accounts.map((account, index) => (
            <div key={account.id} className="flex items-center justify-between gap-3 rounded border border-slate-200 bg-white px-3 py-2 text-sm">
              <span className="truncate">{privacyMode ? `${en ? "Account" : "账号"} ${index + 1}` : account.name}</span>
              <span className="text-slate-500">{account.reason || `${account.active} / ${status.maxConcurrentPerAccount ?? 2}`}</span>
            </div>
          ))}
          {status.accounts.length === 0 && <span className="text-sm text-slate-500">{en ? "Add accounts in Account management." : "请先在账号管理中添加账号。"}</span>}
          {status.recentRequests.length > 0 && (
            <div className="overflow-x-auto">
              <div className="mb-2 text-sm font-semibold">{en ? "Recent requests" : "最近请求"}</div>
              <table className="w-full text-left text-xs">
                <thead><tr>{[en ? "Account" : "账号", en ? "Model" : "模型", en ? "Result" : "结果", en ? "Time" : "耗时"].map((label) => <th key={label} className="py-2">{label}</th>)}</tr></thead>
                <tbody>{status.recentRequests.slice(0, 5).map((request, index) => (
                  <tr key={`${request.at}-${index}`} className="border-t border-slate-200">
                    <td className="py-2">{privacyMode ? "***" : request.account}</td><td>{request.model}</td>
                    <td>{request.outcome === "completed" ? (en ? "Completed" : "完成") : (en ? "Failed / interrupted" : "失败 / 中断")} ({request.status})</td><td>{request.seconds}s</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {!status?.enabled && (status?.activeRequests ?? 0) > 0 && <div className="mt-3 text-sm text-slate-500">{en ? "Finishing active requests" : "正在结束已有请求"}: {status?.activeRequests}</div>}
    </div>
  );
}
