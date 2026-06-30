import type { BackendResponse } from "../types";

export async function invokeLauncher<T>(command: string, payload?: unknown): Promise<T> {
  const response = await window.launcherApi.invoke<T>(command, payload);
  if (!response.ok) {
    throw new Error(response.error || "操作失败");
  }
  return response.data;
}

export async function invokeRaw<T>(command: string, payload?: unknown): Promise<BackendResponse<T>> {
  return window.launcherApi.invoke<T>(command, payload);
}
