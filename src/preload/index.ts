import { contextBridge, ipcRenderer } from "electron";

const projectGitHubUrl = "https://github.com/lljycyp/Codex-Forge";
const projectGiteeUrl = "https://gitee.com/llj20010218/codex-forge";

contextBridge.exposeInMainWorld("launcherApi", {
  invoke: (command: string, payload?: unknown) => ipcRenderer.invoke("launcher:invoke", command, payload ?? {}),
  selectDirectory: (defaultPath?: string) => ipcRenderer.invoke("launcher:select-directory", defaultPath),
  selectAuthJsonFile: () => ipcRenderer.invoke("launcher:select-auth-json-file"),
  selectProfileBackupFile: () => ipcRenderer.invoke("launcher:select-profile-backup-file"),
  onBackendProgress: (callback: (progress: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, progress: unknown) => callback(progress);
    ipcRenderer.on("launcher:backend-progress", listener);
    return () => ipcRenderer.removeListener("launcher:backend-progress", listener);
  },
  getAutoStartEnabled: () => ipcRenderer.invoke("app:get-auto-start-enabled"),
  getAppVersion: () => ipcRenderer.invoke("app:get-version"),
  openProjectGitHub: () => ipcRenderer.invoke("app:open-external", projectGitHubUrl),
  openProjectGitee: () => ipcRenderer.invoke("app:open-external", projectGiteeUrl),
  setAutoStartEnabled: (enabled: boolean) => ipcRenderer.invoke("app:set-auto-start-enabled", enabled),
  onUpdateEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, updateEvent: unknown) => callback(updateEvent);
    ipcRenderer.on("app:update-event", listener);
    return () => ipcRenderer.removeListener("app:update-event", listener);
  },
  checkForUpdates: () => ipcRenderer.invoke("app:update-check"),
  downloadUpdate: () => ipcRenderer.invoke("app:update-download"),
  installUpdate: () => ipcRenderer.invoke("app:update-install"),
  minimizeWindow: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximizeWindow: () => ipcRenderer.invoke("window:toggle-maximize"),
  closeWindow: () => ipcRenderer.invoke("window:close")
});
