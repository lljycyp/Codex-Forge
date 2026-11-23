import { createInterface } from "node:readline";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { spawnGateway } from "./python/launcherBackend";

type Reply = { ok: boolean; data: Record<string, unknown>; error: string };
const failure = (error: string): Reply => ({ ok: false, data: {}, error });
const commands = new Set(["status", "service", "launch", "share", "key", "policy", "export_client_bundle"]);
const pending = new Map<number, (reply: Reply) => void>();
const root = join(process.env.LOCALAPPDATA ?? "", "CodexForge", "gateway");
let child: ReturnType<typeof spawnGateway> | undefined;
let sequence = 0;
let closing = false;
export let gatewayShared = false;

function worker() {
  if (child) return child;
  const process = spawnGateway();
  child = process;
  process.stderr.resume();
  const lines = createInterface({ input: process.stdout });
  lines.on("line", (line) => {
    try {
      const msg = JSON.parse(line) as Reply & { id: number };
      pending.get(msg.id)?.(msg);
    } catch {
      // Only framed replies can resolve a request.
    }
  });
  const exited = () => {
    if (child !== process) return;
    child = undefined;
    gatewayShared = false;
    for (const resolve of pending.values()) resolve(failure("网关进程已退出"));
    lines.close();
  };
  process.once("exit", exited);
  process.once("error", exited);
  process.stdin.on("error", exited);
  return process;
}

export function gatewayCommand(command: string, payload: unknown = {}): Promise<Reply> {
  if (closing || !commands.has(command)) return Promise.resolve(failure("网关命令不可用"));
  const id = ++sequence;
  const proc = worker();
  return new Promise((resolve) => {
    const finish = (value: Reply) => {
      clearTimeout(timer);
      pending.delete(id);
      if (value.ok && typeof value.data.shared === "boolean") gatewayShared = value.data.shared;
      resolve(value);
    };
    const timer = setTimeout(() => finish(failure("等待网关超时，请刷新状态确认结果")), 60000);
    pending.set(id, finish);
    proc.stdin.write(JSON.stringify({ id, command, payload }) + "\n", (err) => {
      if (err && pending.has(id)) finish(failure("无法连接网关进程"));
    });
  });
}

export function restoreGateway() {
  if (existsSync(join(root, "gateway.sqlite"))) void gatewayCommand("status");
}

export function closeGateway() {
  closing = true;
  child?.stdin.end();
}
