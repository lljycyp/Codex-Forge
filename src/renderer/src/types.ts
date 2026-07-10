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
  shareSystemConfig: boolean;
  launchMode: "switch" | "multi";
  profileRoot: string;
  profileRootExists: boolean;
  profileCount: number;
  runningCount: number;
};

export type ViewKey = "home" | "profiles" | "instructions" | "toml" | "settings";

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
  codexHome?: string;
  codexHomeExists?: boolean;
  portableCodexPath?: string;
  portableCodexExists?: boolean;
  portableCodexSizeBytes?: number;
  portableCodexSizeText?: string;
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

export type InstructionTemplate = {
  id: string;
  title: string;
  filename: string;
  content: string;
  enabled: boolean;
};

export type InstructionTemplateState = {
  templates: InstructionTemplate[];
  currentInstructionFile: string;
  activeConfigPath: string;
};

export type TomlConfigState = {
  path: string;
  exists: boolean;
  content: string;
  backupPath?: string;
};

export type UpdateEvent =
  | { status: "available"; currentVersion: string; version: string; releaseNotes?: string }
  | {
      status: "downloading";
      currentVersion: string;
      version: string;
      percent: number;
      transferred: number;
      total: number;
      bytesPerSecond: number;
    }
  | { status: "downloaded"; currentVersion: string; version: string; releaseNotes?: string }
  | { status: "not-available"; currentVersion: string; version: string; manual: boolean }
  | { status: "error"; message: string };

export type LauncherApi = {
  invoke: <T>(command: string, payload?: unknown) => Promise<BackendResponse<T>>;
  selectDirectory: (defaultPath?: string) => Promise<string>;
  selectAuthJsonFile: () => Promise<string>;
  selectProfileBackupFile?: () => Promise<string>;
  getAutoStartEnabled?: () => Promise<boolean>;
  getAppVersion?: () => Promise<string>;
  openProjectGitHub?: () => Promise<void>;
  openProjectGitee?: () => Promise<void>;
  setAutoStartEnabled?: (enabled: boolean) => Promise<boolean>;
  onUpdateEvent?: (callback: (event: UpdateEvent) => void) => () => void;
  checkForUpdates?: () => Promise<void>;
  downloadUpdate?: () => Promise<void>;
  installUpdate?: () => Promise<void>;
  minimizeWindow: () => Promise<void>;
  toggleMaximizeWindow: () => Promise<void>;
  closeWindow: () => Promise<void>;
};

declare global {
  interface Window {
    launcherApi: LauncherApi;
  }
}
