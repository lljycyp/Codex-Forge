import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from "antd";
import { Copy, Download, KeyRound, Network, Plus } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";

type AccessKey = {
  id: string; name: string; cap: number | string | null; enabled: number | boolean; expires: number;
  calls: number; active: number; waiting: number; websocketConnections?: number; websocketLimit?: number;
};
type Account = { id: string; name: string; cap: number; enabled: boolean; active: number; reason: string };
type Log = {
  id: string; at: number; owner: string; account: string; model: string; protocol: string; result: string; ms: number;
  inputTokens?: number; cachedTokens?: number; outputTokens?: number; continuations?: number;
};
type WebSocketRejection = {
  at: number; ownerId: string; ownerName: string; keyConnections: number; totalConnections: number;
  keyLimit?: number;
};
type UpstreamForbidden = {
  at: number; account: string; operation: string; code: string;
  reason: "site_block" | "provider_error" | "websocket_handshake" | "forbidden";
};
const upstreamReasons: Record<UpstreamForbidden["reason"], string> = {
  site_block: "站点拦截",
  provider_error: "上游服务返回错误码",
  websocket_handshake: "上游 WebSocket 握手被拒绝",
  forbidden: "上游未提供拒绝详情",
};
type Status = {
  enabled: boolean; shared: boolean; base: string; lanBase: string; port: number; address: string;
  addresses: string[]; ca: string; keys: AccessKey[]; accounts: Account[]; records: Log[];
  waiting: number; active: number; error: string;
  workspaceFailure?: { at: number; route: string; status: number } | null;
  lastUpstreamForbidden?: UpstreamForbidden | null;
  websocket?: { connections: number; perKeyLimit: number; lastRejection: WebSocketRejection | null };
};
const panel = "grid grid-cols-1 gap-4 rounded-panel border border-shell-line bg-white p-5";
const heading = "m-0 text-base font-bold text-slate-900";

export function GatewayPage() {
  const { t } = useI18n();
  const formatCount = (n?: number) => n == null ? t("未知") : n.toLocaleString();
  const [status, setStatus] = useState<Status>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [address, setAddress] = useState("");
  const [port, setPort] = useState<number>();
  const [keyEditor, setKeyEditor] = useState<"create" | AccessKey>();
  const [name, setName] = useState("");
  const [websocketLimit, setWebsocketLimit] = useState<number | null>(null);
  const [cap, setCap] = useState("2");
  const [unlimited, setUnlimited] = useState(false);
  const [days, setDays] = useState(0);
  const [freshKey, setFreshKey] = useState("");
  const updating = useRef(false);
  const epoch = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++epoch.current;
    try {
      const next = await invokeLauncher<Status>("gateway_status");
      if (ticket === epoch.current) { setStatus(next); setError(next.error); }
    } catch (err) {
      if (ticket === epoch.current) setError(err instanceof Error ? err.message : String(err));
    }
  }, []);
  useEffect(() => {
    let mounted = true;
    let timer: number;
    let first = true;
    const poll = async () => {
      if (!updating.current && (first || !document.hidden)) await refresh();
      first = false;
      if (mounted) timer = window.setTimeout(poll, 3000);
    };
    void poll();
    return () => { mounted = false; epoch.current++; window.clearTimeout(timer); };
  }, [refresh]);

  async function change(command: string, payload: Record<string, unknown>) {
    if (updating.current) return;
    updating.current = true;
    epoch.current++;
    setBusy(true);
    try {
      const res = await invokeLauncher<{ key?: string; saved?: boolean }>("gateway_" + command, payload);
      if (res.key) { setKeyEditor(undefined); setName(""); setFreshKey(res.key); }
      if (command === "key" && payload.action === "edit") {
        setKeyEditor(undefined);
        message.success(t("已保存"));
      }
      if (command === "export_client_bundle" && res.saved) message.success(t("已导出 Codex 接入包"));
      await refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      updating.current = false;
      setBusy(false);
    }
  }

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); message.success(t("已复制")); }
    catch { message.error(t("复制失败，请手动复制")); }
  }
  function openKeyEditor(key: "create" | AccessKey) {
    setKeyEditor(key);
    setName(key === "create" ? "" : key.name);
    setWebsocketLimit(key === "create" ? null : key.websocketLimit ?? status?.websocket?.perKeyLimit ?? null);
    setCap(key === "create" || key.cap === null ? "2" : String(key.cap));
    setUnlimited(key !== "create" && key.cap === null);
  }

  const creating = keyEditor === "create";
  const capValid = unlimited || /^0*[1-9][0-9]*$/.test(cap.trim());
  const websocketLimitValid = websocketLimit !== null && Number.isSafeInteger(websocketLimit) && websocketLimit > 0;
  const keyValid = !!name.trim() && capValid && (creating || websocketLimitValid);
  function saveKey() {
    if (!keyEditor || !keyValid) return;
    const limit = unlimited ? null : cap.trim();
    if (keyEditor === "create") {
      void change("key", { action: "create", name, cap: limit, days });
    } else {
      void change("key", { action: "edit", id: keyEditor.id, name, cap: limit, websocketLimit });
    }
  }

  const workspaceFailure = status?.workspaceFailure;
  const upstreamForbidden = status?.lastUpstreamForbidden;
  const websocket = status?.websocket;
  const rejection = websocket?.lastRejection;
  const selectedAddress = address || status?.address || status?.addresses[0] || "";
  const selectedPort = port ?? status?.port ?? 19381;
  const snippet = [
    'model_provider = "forge"', "", "[model_providers.forge]", 'name = "Forge"',
    `base_url = "${status?.lanBase || ""}"`, 'wire_api = "responses"', 'env_key = "FORGE_GATEWAY_KEY"',
    "supports_websockets = true", "request_max_retries = 0", "stream_max_retries = 0",
  ].join("\n");
  return <div className="mx-auto grid w-full max-w-[1320px] grid-cols-1 gap-4">
    {error ? <Alert showIcon type="error" message={error} /> : null}
    {workspaceFailure && <Alert showIcon type="warning" message={t("Codex 启动时工作空间查询失败")}
      description={[
        new Date(workspaceFailure.at * 1000).toLocaleString(),
        workspaceFailure.route,
        `HTTP ${workspaceFailure.status}`,
      ].join(" · ")} />}
    {upstreamForbidden && <Alert showIcon type="warning" message={t("最近一次网关上游拒绝（HTTP 403）")}
      description={[
        new Date(upstreamForbidden.at * 1000).toLocaleString(),
        `${t("池内账号")} ${upstreamForbidden.account}`,
        upstreamForbidden.operation,
        t(upstreamReasons[upstreamForbidden.reason]),
        ...(upstreamForbidden.reason === "provider_error" ? [upstreamForbidden.code] : []),
      ].join(" · ")} />}
    <section className={panel}>
      <div className="flex items-center justify-between gap-3">
        <h2 className={heading}><Network className="mr-2 inline" size={17} />{t("网关服务")}</h2>
        <Switch aria-label={t("网关服务")} checked={!!status?.enabled} disabled={busy || !status}
          onChange={(enabled) => void change("service", { enabled })} />
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600">
        <Tag color={status?.enabled ? "green" : "default"}>{t(status?.enabled ? "运行中" : "已停止")}</Tag>
        <span>{t("本机地址")} <code>{status?.base || "—"}</code></span>
        <span title={t("占用包含正在握手的连接")}>
          {t("WebSocket 总连接")} <strong>{websocket?.connections ?? "—"}</strong>
        </span>
        <span>{t("正在处理")} <strong>{status?.active ?? 0}</strong></span>
        <span>{t("排队")} <strong>{status?.waiting ?? 0}</strong></span>
      </div>
      {websocket && rejection ? <Alert showIcon type="warning"
        message={`${t("最近一次 WebSocket 握手 429")} · ${t("该 Key 连接已满")}`}
        description={<div className="flex flex-wrap gap-x-4 gap-y-1">
          <span>{new Date(rejection.at * 1000).toLocaleString()}</span>
          <span>{t("来源")} {rejection.ownerId === "local" ? t("本机") : rejection.ownerName}</span>
          <span>{t("WebSocket 连接")} {rejection.keyConnections} / {rejection.keyLimit ?? websocket.perKeyLimit}</span>
          <span>{t("WebSocket 总连接")} {rejection.totalConnections}</span>
        </div>} /> : null}
    </section>
    <section className={panel}>
      <div className="flex items-center justify-between gap-3">
        <h2 className={heading}>{t("局域网共享")}</h2>
        <Switch aria-label={t("局域网共享")} checked={!!status?.shared} disabled={busy || !status || (!selectedAddress && !status.shared)}
          onChange={(enabled) => void change("share", { enabled, address: selectedAddress, port: selectedPort })} />
      </div>
      <Space wrap>
        <label>{t("监听地址")} <Select aria-label={t("监听地址")} value={selectedAddress || undefined} style={{ minWidth: 160 }}
          disabled={busy || status?.shared} onChange={setAddress} options={status?.addresses.map(value => ({ value }))} /></label>
        <label>{t("端口")} <InputNumber aria-label={t("端口")} min={1} max={65535} value={selectedPort}
          disabled={busy || status?.shared} onChange={n => setPort(n ?? undefined)} /></label>
      </Space>
      {status?.shared ? <div className="grid gap-2 text-sm">
        <Input readOnly aria-label="LAN Base URL" value={status.lanBase} addonBefore="Base URL" />
        <Space wrap>
          <Button type="primary" icon={<Download size={14} />} disabled={busy}
            onClick={() => void change("export_client_bundle", {})}>{t("导出 Codex 接入包")}</Button>
          <Button icon={<Copy size={14} />} onClick={() => void copy(snippet)}>{t("复制客户端配置")}</Button>
        </Space>
        <span className="text-slate-600">{t("在对方的 Windows 电脑解压接入包，关闭 Codex 后运行 Apply-Forge-Gateway.cmd，再打开原版 Codex 填写个人 Key。")}</span>
        <span className="text-slate-500">{t("手动接入时，将配置片段合并到 config.toml，设置 FORGE_GATEWAY_KEY，并将 CODEX_CA_CERTIFICATE 指向从接入包解压出的 forge-gateway-ca.pem（绝对路径）。")}</span>
      </div> : null}
    </section>
    <section className={panel}>
      <div className="flex items-center justify-between">
        <h2 className={heading}><KeyRound size={16} className="mr-2 inline" />{t("访问 Key")}</h2>
        <Button type="primary" icon={<Plus size={15} />} disabled={busy || !status} onClick={() => openKeyEditor("create")}>{t("创建 Key")}</Button>
      </div>
      <Table<AccessKey> size="small" rowKey="id" pagination={false} scroll={{ x: 740 }} dataSource={status?.keys || []}
        columns={[
          { title: t("名称"), dataIndex: "name", render: (v: string, row) => row.id === "local" ? t("本机") : v },
          { title: t("WebSocket 连接"), render: (_, row) => (
            <span className="whitespace-nowrap" title={t("占用包含正在握手的连接")}>
              {websocket && row.websocketConnections !== undefined ? `${row.websocketConnections} / ${row.websocketLimit ?? websocket.perKeyLimit}` : "—"}
            </span>
          ) },
          { title: t("生成并发"), render: (_, row) => {
            const value = `${row.active} / ${row.cap ?? t("不限制")}`;
            return <span className="block max-w-40 truncate" title={value}>{value}</span>;
          } }, { title: t("排队"), dataIndex: "waiting" },
          { title: t("请求数"), dataIndex: "calls" },
          { title: t("有效期"), dataIndex: "expires", render: n => n ? new Date(n*1000).toLocaleDateString() : t("长期") },
          { title: t("启用"), render: (_, row) => <Switch size="small" aria-label={t("启用")} checked={!!row.enabled} disabled={busy || row.id === "local"}
            onChange={enabled => void change("key", { action:"toggle", id:row.id, enabled })} /> },
          { title: t("操作"), render: (_, row) => row.id === "local" ? t("本机专用") : <Space>
            <Button type="link" size="small" disabled={busy} onClick={() => openKeyEditor(row)}>{t("编辑")}</Button>
            <Popconfirm title={t("轮换后原 Key 将失效")} onConfirm={() => change("key", { action:"rotate", id:row.id })}>
              <Button type="link" size="small" disabled={busy}>{t("轮换")}</Button></Popconfirm>
            <Popconfirm title={t("撤销此 Key 并清除其临时文件和续接状态？")} onConfirm={() => change("key", { action:"revoke", id:row.id })}>
              <Button type="link" danger size="small" disabled={busy}>{t("撤销")}</Button></Popconfirm>
          </Space> },
        ]} />
    </section>
    <section className={panel}>
      <h2 className={heading}>{t("参与调度的账号")}</h2>
      <Table<Account> rowKey="id" size="small" pagination={false} dataSource={status?.accounts || []} columns={[
        { title:t("账号"), dataIndex:"name" },
        { title:t("状态"), render:(_, row) => t(row.reason || (row.enabled ? "可用" : "已停用")) },
        { title:t("正在处理"),dataIndex:"active" },
        { title:t("并发上限"),render:(_, row) => <Select aria-label={t("并发上限")} size="small" disabled={busy} value={row.cap}
          options={Array.from({length:32}, (_, i) => ({value:i+1}))}
          onChange={next => void change("policy", {id:row.id,enabled:row.enabled,cap:next})} /> },
        { title:t("参与"),render:(_, row) => <Switch size="small" aria-label={t("参与")} disabled={busy} checked={row.enabled}
          onChange={enabled => void change("policy", {id:row.id,enabled,cap:row.cap})} /> },
      ]} />
    </section>
    <section className={panel}>
      <h2 className={heading}>{t("最近请求")}</h2>
      <Table<Log> rowKey="id" size="small" pagination={{pageSize:8,hideOnSinglePage:true}} scroll={{ x: 940 }} dataSource={status?.records || []}
        columns={[
          {title:t("时间"),dataIndex:"at",render:n => new Date(n*1000).toLocaleTimeString()},
          {title:t("来源"),dataIndex:"owner"},
          {title:t("账号"),dataIndex:"account"}, {title:t("模型"),dataIndex:"model"},
          {title:t("协议"),dataIndex:"protocol"}, {title:t("结果"),dataIndex:"result"},
          {title:t("输入 Token"),dataIndex:"inputTokens",align:"right",render:formatCount},
          {title:t("缓存命中 Token"),dataIndex:"cachedTokens",align:"right",render:formatCount},
          {title:t("输出 Token"),dataIndex:"outputTokens",align:"right",render:formatCount},
          {title:t("续写次数"),dataIndex:"continuations",align:"right",render:formatCount},
          {title:t("耗时"),dataIndex:"ms",render:n => (n/1000).toFixed(1)+" s"},
        ]} />
    </section>
    <Modal title={t(creating ? "创建 Key" : "编辑 Key")} open={!!keyEditor} confirmLoading={busy}
      okText={t("保存")} cancelText={t("取消")} okButtonProps={{ disabled: !keyValid }}
      onCancel={() => { if (!busy) setKeyEditor(undefined); }} onOk={saveKey}>
      <div className="grid gap-3">
        <label>{t("使用者名称")}<Input autoFocus maxLength={64} disabled={busy} value={name} onChange={e => setName(e.target.value)} /></label>
        {!creating && <label>{t("WebSocket 连接上限")} <InputNumber min={1} max={Number.MAX_SAFE_INTEGER}
          disabled={busy} value={websocketLimit} onChange={setWebsocketLimit}
          status={websocketLimitValid ? undefined : "error"} aria-invalid={!websocketLimitValid}
          aria-describedby={websocketLimitValid ? undefined : "gateway-key-ws-limit-error"} /></label>}
        {!creating && !websocketLimitValid && <span id="gateway-key-ws-limit-error" className="text-sm text-red-600">
          {t("WebSocket 连接上限必须为正整数")}
        </span>}
        <Space wrap>
          <label>{t("生成并发上限")} <Input inputMode="numeric" value={unlimited ? "" : cap} disabled={busy || unlimited}
            className="w-40" status={capValid ? undefined : "error"} aria-invalid={!capValid}
            aria-describedby={capValid ? undefined : "gateway-key-cap-error"} onChange={e => setCap(e.target.value)} /></label>
          <Checkbox disabled={busy} checked={unlimited} onChange={e => setUnlimited(e.target.checked)}>{t("不限制")}</Checkbox>
        </Space>
        {!capValid && <span id="gateway-key-cap-error" className="text-sm text-red-600">{t("请输入正整数或选择不限制")}</span>}
        {creating && <label>{t("有效天数（0 为长期）")} <InputNumber min={0} max={3650} disabled={busy} value={days} onChange={v => setDays(v ?? 0)} /></label>}
      </div>
    </Modal>
    <Modal title={t("保存个人 Key")} open={!!freshKey} footer={<Space>
      {status?.shared ? <Button icon={<Download size={14} />} disabled={busy}
        onClick={() => void change("export_client_bundle", {})}>{t("导出 Codex 接入包")}</Button> : null}
      <Button onClick={() => setFreshKey("")}>{t("关闭")}</Button>
    </Space>}
      onCancel={() => setFreshKey("")}>
      <p>{t("完整 Key 仅在此显示一次。")}</p>
      <Input readOnly aria-label="Gateway Key" value={freshKey} addonAfter={<Button size="small" type="text"
        icon={<Copy size={14} />} onClick={() => void copy(freshKey)}>{t("复制")}</Button>} />
    </Modal>
  </div>;
}
