export type BackendResponse<T> = {
  ok: boolean;
  data: T;
  error: string;
};

export type AppState = {
  codexCommandAvailable: boolean;
  activeAuthPath: string;
  activeAuthExists: boolean;
  activeConfigPath: string;
  activeConfigExists: boolean;
  activeProfile: string;
  profileRoot: string;
  profileRootExists: boolean;
  profileCount: number;
  runningCount: number;
};

export type ViewKey = "profiles" | "settings";

export type ViewMeta = {
  title: string;
  description: string;
};

export type RunCommandOptions = {
  blocking?: boolean;
  refreshAfter?: boolean;
};

export type RunCommand = (
  command: string,
  payload?: unknown,
  successText?: string,
  options?: RunCommandOptions,
) => Promise<void>;

export type ProfileSummary = {
  name: string;
  running: boolean;
  active: boolean;
  profileDir: string;
  profileDirExists: boolean;
  authPath: string;
  authExists: boolean;
  configPath: string;
  configExists: boolean;
  usage: ProfileUsage | null;
};

export type ProfileUsageWindow = {
  usedPercent: number;
  remainingPercent: number;
  windowSeconds: number;
  resetAt: number | null;
};

export type ProfileUsage = {
  fetchedAt: number;
  planType: string | null;
  fiveHour: ProfileUsageWindow | null;
  oneWeek: ProfileUsageWindow | null;
  error: string | null;
};

export type LauncherApi = {
  invoke: <T>(command: string, payload?: unknown) => Promise<BackendResponse<T>>;
  selectDirectory: (defaultPath?: string) => Promise<string>;
  getAutoStartEnabled?: () => Promise<boolean>;
  setAutoStartEnabled?: (enabled: boolean) => Promise<boolean>;
  minimizeWindow: () => Promise<void>;
  toggleMaximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
};

declare global {
  interface Window {
    launcherApi: LauncherApi;
  }
}
