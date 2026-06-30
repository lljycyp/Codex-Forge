export type BackendResponse<T> = {
  ok: boolean;
  data: T;
  error: string;
};

export type AppState = {
  codexPath: string;
  codexExists: boolean;
  codexVersion: string;
  profileRoot: string;
  profileRootExists: boolean;
  profileCount: number;
  runningCount: number;
  sessionSyncEnabled: boolean;
  memorySyncEnabled: boolean;
};

export type ViewKey = "dashboard" | "profiles" | "settings" | "diagnostics";

export type ViewMeta = {
  title: string;
  description: string;
};

export type RunCommand = (command: string, payload?: unknown, successText?: string) => Promise<void>;

export type ProfileSummary = {
  name: string;
  running: boolean;
  profileDir: string;
  profileDirExists: boolean;
  codexHome: string;
  codexHomeExists: boolean;
  portableCodexPath: string;
  portableCodexExists: boolean;
};

export type DiagnosticsData = {
  basic: Record<string, string | number | boolean>;
  profiles: Array<ProfileSummary & {
    statusText: string;
    errors: string[];
    warnings: string[];
    memoryDatabase: string;
    diskUsageBytes: number;
    diskUsageText: string;
  }>;
};

export type LauncherApi = {
  invoke: <T>(command: string, payload?: unknown) => Promise<BackendResponse<T>>;
  selectDirectory: (defaultPath?: string) => Promise<string>;
  minimizeWindow: () => Promise<void>;
  toggleMaximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
};

declare global {
  interface Window {
    launcherApi: LauncherApi;
  }
}
