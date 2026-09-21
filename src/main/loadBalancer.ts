import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import { invokeBackend, spawnLoadBalancer } from "./python/launcherBackend";

type Result = { ok: boolean; data: Record<string, unknown>; error: string };
let child: ChildProcessWithoutNullStreams | null = null;
let starting: Promise<void> | null = null;
let sequence = 0;
let lastError = "";
let quitting = false;
let operations: Promise<unknown> = Promise.resolve();
const pending = new Map<number, { resolve: (result: Result) => void; timer: NodeJS.Timeout }>();

function failure(error: string): Result {
  return { ok: false, data: {}, error };
}

async function ensureService(): Promise<void> {
  if (quitting) throw new Error("Forge 正在退出");
  if (starting) return starting;
  if (child) return;
  starting = new Promise<void>((resolve, reject) => {
    const process = spawnLoadBalancer();
    child = process;
    let ready = false;
    const timer = setTimeout(() => {
      process.kill();
      reject(new Error("负载均衡网关启动超时"));
    }, 10000);
    const lines = createInterface({ input: process.stdout });
    process.stderr.resume(); // Never send raw subprocess errors or credentials to the UI.
    process.stdin.on("error", () => undefined);
    const exited = () => {
      clearTimeout(timer);
      lines.close();
      if (child !== process) return;
      child = null;
      if (!quitting) lastError = "网关已停止；请关闭后重新开启。若启动失败，请检查端口 19380 是否被占用。";
      for (const { resolve: finish, timer: timeout } of pending.values()) {
        clearTimeout(timeout);
        finish(failure("负载均衡网关已退出"));
      }
      pending.clear();
      if (!ready) reject(new Error(lastError || "网关启动失败"));
    };
    process.once("error", exited);
    process.once("exit", exited);
    lines.on("line", (line) => {
      let response: Result & { id: number };
      try {
        response = JSON.parse(line) as Result & { id: number };
      } catch {
        return;
      }
      if (response.id === 0 && !ready) {
        ready = true;
        clearTimeout(timer);
        lastError = "";
        resolve();
        return;
      }
      const request = pending.get(response.id);
      if (!request) return;
      pending.delete(response.id);
      clearTimeout(request.timer);
      request.resolve(response);
    });
  });
  try {
    await starting;
  } finally {
    starting = null;
  }
}

function request(command: string, enabled?: boolean): Promise<Result> {
  const process = child;
  if (!process) return Promise.resolve(failure("负载均衡网关未启动"));
  const id = ++sequence;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      resolve(failure("网关操作超时，请刷新状态"));
    }, command === "launch_client" ? 30000 : 10000);
    pending.set(id, { resolve, timer });
    process.stdin.write(JSON.stringify({ id, command, enabled }) + "\n", (error) => {
      if (!error || !pending.has(id)) return;
      pending.delete(id);
      clearTimeout(timer);
      resolve(failure("无法连接负载均衡网关"));
    });
  });
}

export function handleLoadBalancer(command: string, payload: unknown): Promise<Result> {
  const operation = operations.then(async (): Promise<Result> => {
    try {
      if (command === "set_load_balancer_enabled") {
        const enabled = (payload as { enabled?: unknown } | null)?.enabled;
        if (typeof enabled !== "boolean") return failure("enabled 必须是布尔值");
        if (!enabled && !child) {
          const result = await invokeBackend("disable_load_balancer", {});
          lastError = "";
          return result.ok ? { ok: true, data: { ...result.data, running: false, activeRequests: 0, accounts: [], recentRequests: [] }, error: "" } : result;
        }
        await ensureService();
        return await request("set_enabled", enabled);
      }
      if (command === "get_load_balancer_key") return await request("get_key");
      if (command === "launch_load_balancer_client") return await request("launch_client");
      if (child) return await request("status");
      const result = await invokeBackend("get_load_balancer_preferences", {});
      return result.ok ? { ok: true, data: { ...result.data, running: false, activeRequests: 0,
        baseUrl: `http://127.0.0.1:${result.data.port}/v1`, accounts: [], recentRequests: [], error: lastError }, error: "" } : result;
    } catch (error) {
      return failure(error instanceof Error ? error.message : "负载均衡操作失败");
    }
  });
  operations = operation;
  return operation;
}

export function restoreLoadBalancer(): Promise<unknown> {
  const operation = operations.then(async () => {
    const settings = await invokeBackend("get_load_balancer_preferences", {});
    if (settings.ok && settings.data.enabled === true) {
      try { await ensureService(); } catch { /* Status reports startup failure. */ }
    }
  });
  operations = operation.catch(() => undefined);
  return operations;
}

export async function shutdownLoadBalancer(): Promise<void> {
  quitting = true;
  const process = child;
  if (!process) return;
  await new Promise<void>((resolve) => {
    const timer = setTimeout(() => { process.kill(); resolve(); }, 2000);
    process.once("exit", () => { clearTimeout(timer); resolve(); });
    process.stdin.end();
  });
}
