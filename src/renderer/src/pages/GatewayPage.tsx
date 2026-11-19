import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Input, InputNumber, Modal, Popconfirm, Select, Space, Switch, Table, Tag, message } from "antd";
import { Copy, KeyRound, Network, Plus } from "lucide-react";
import { invokeLauncher } from "../api/launcher";
import { useI18n } from "../i18n";

type AccessKey = { id: string; name: string; cap: number; enabled: number; expires: number; calls: number; active: number; waiting: number };
type Account = { id: string; name: string; cap: number; enabled: boolean; active: number; reason: string };
type Log = { id: string; at: number; owner: string; account: string; model: string; protocol: string; result: string; ms: number };
type Status = {
  enabled: boolean; shared: boolean; base: string; lanBase: string; port: number; address: string;
  addresses: string[]; ca: string; keys: AccessKey[]; accounts: Account[]; records: Log[];
  waiting: number; active: number; error: string;
};
const panel = "grid gap-4 rounded-panel border border-shell-line bg-white p-5";
const heading = "m-0 text-base font-bold text-slate-900";

export function GatewayPage({ privacy }: { privacy: boolean }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<Status>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [address, setAddress] = useState("");
  const [port, setPort] = useState<number>();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [cap, setCap] = useState(2);
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
      const res = await invokeLauncher<{ key?: string }>("gateway_" + command, payload);
      if (res.key) { setCreating(false); setName(""); setFreshKey(res.key); }
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
  const showName = (value: string) => privacy ? "••••" : value;
  const selectedAddress = address || status?.address || status?.addresses[0] || "";
  const selectedPort = port ?? status?.port ?? 19381;
  const snippet = [
    'model_provider = "forge"', "", "[model_providers.forge]", 'name = "Forge"',
    `base_url = "${status?.lanBase || ""}"`, 'wire_api = "responses"', 'env_key = "FORGE_GATEWAY_KEY"',
    "supports_websockets = true", "request_max_retries = 0", "stream_max_retries = 0",
  ].join("\n");
  return <div className="mx-auto grid w-full max-w-[1320px] gap-4">
    {error ? <Alert showIcon type="error" message={error} /> : null}
    <section className={panel}>
      <div className="flex items-center justify-between gap-3">
        <h2 className={heading}><Network className="mr-2 inline" size={17} />{t("网关服务")}</h2>
        <Switch aria-label={t("网关服务")} checked={!!status?.enabled} disabled={busy || !status}
          onChange={(enabled) => void change("service", { enabled })} />
      </div>
      <div className="flex flex-wrap items-center gap-4 text-sm text-slate-600">
        <Tag color={status?.enabled ? "green" : "default"}>{t(status?.enabled ? "运行中" : "已停止")}</Tag>
        <span>{t("本机地址")} <code>{status?.base || "—"}</code></span>
        <span>{t("正在处理")} <strong>{status?.active ?? 0}</strong></span>
        <span>{t("排队")} <strong>{status?.waiting ?? 0}</strong></span>
      </div>
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
          <Button icon={<Copy size={14} />} onClick={() => void copy(snippet)}>{t("复制客户端配置")}</Button>
          <Button disabled={busy} onClick={() => void change("export_ca", {})}>{t("导出信任证书")}</Button>
        </Space>
        <span className="text-slate-600">{t("将配置合并到对方的 config.toml。在启动该客户端的环境中，FORGE_GATEWAY_KEY 填个人 Key，CODEX_CA_CERTIFICATE 填导出的 PEM 文件绝对路径。")}</span>
      </div> : null}
    </section>
    <section className={panel}>
      <div className="flex items-center justify-between">
        <h2 className={heading}><KeyRound size={16} className="mr-2 inline" />{t("访问 Key")}</h2>
        <Button type="primary" icon={<Plus size={15} />} disabled={busy || !status} onClick={() => setCreating(true)}>{t("创建 Key")}</Button>
      </div>
      <Table<AccessKey> size="small" rowKey="id" pagination={false} scroll={{ x: 600 }} dataSource={status?.keys || []}
        columns={[
          { title: t("名称"), dataIndex: "name", render: (v: string) => showName(v) },
          { title: t("并发"), render: (_, row) => row.active + " / " + row.cap }, { title: t("排队"), dataIndex: "waiting" },
          { title: t("请求数"), dataIndex: "calls" },
          { title: t("有效期"), dataIndex: "expires", render: n => n ? new Date(n*1000).toLocaleDateString() : t("长期") },
          { title: t("启用"), render: (_, row) => <Switch size="small" aria-label={t("启用")} checked={!!row.enabled} disabled={busy}
            onChange={enabled => void change("key", { action:"toggle", id:row.id, enabled })} /> },
          { title: t("操作"), render: (_, row) => <Space>
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
        { title:t("账号"), dataIndex:"name", render:(v:string) => showName(v) },
        { title:t("状态"), render:(_, row) => row.reason || t(row.enabled ? "可用" : "已停用") },
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
      <Table<Log> rowKey="id" size="small" pagination={{pageSize:8,hideOnSinglePage:true}} scroll={{ x: 590 }} dataSource={status?.records || []}
        columns={[
          {title:t("时间"),dataIndex:"at",render:n => new Date(n*1000).toLocaleTimeString()},
          {title:t("来源"),dataIndex:"owner",render:(v:string) => showName(v)},
          {title:t("账号"),dataIndex:"account",render:(v:string) => showName(v)}, {title:t("模型"),dataIndex:"model"},
          {title:t("协议"),dataIndex:"protocol"}, {title:t("结果"),dataIndex:"result"},
          {title:t("耗时"),dataIndex:"ms",render:n => (n/1000).toFixed(1)+" s"},
        ]} />
    </section>
    <Modal title={t("创建 Key")} open={creating} confirmLoading={busy} okButtonProps={{ disabled:!name.trim() }}
      onCancel={() => setCreating(false)} onOk={() => void change("key",{action:"create",name,cap,days})}>
      <div className="grid gap-3">
        <label>{t("使用者名称")}<Input autoFocus maxLength={64} value={name} onChange={e => setName(e.target.value)} /></label>
        <Space wrap>
          <label>{t("并发上限")} <InputNumber min={1} max={32} value={cap} onChange={v => setCap(v ?? 2)} /></label>
          <label>{t("有效天数（0 为长期）")} <InputNumber min={0} max={3650} value={days} onChange={v => setDays(v ?? 0)} /></label>
        </Space>
      </div>
    </Modal>
    <Modal title={t("保存个人 Key")} open={!!freshKey} footer={<Button onClick={() => setFreshKey("")}>{t("关闭")}</Button>}
      onCancel={() => setFreshKey("")}>
      <p>{t("完整 Key 仅在此显示一次。")}</p>
      <Input readOnly aria-label="Gateway Key" value={freshKey} addonAfter={<Button size="small" type="text"
        icon={<Copy size={14} />} onClick={() => void copy(freshKey)}>{t("复制")}</Button>} />
    </Modal>
  </div>;
}
