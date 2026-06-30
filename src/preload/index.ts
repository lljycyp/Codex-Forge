import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("launcherApi", {
  invoke: (command: string, payload?: unknown) => ipcRenderer.invoke("launcher:invoke", command, payload ?? {}),
  selectDirectory: (defaultPath?: string) => ipcRenderer.invoke("launcher:select-directory", defaultPath),
  minimizeWindow: () => ipcRenderer.invoke("window:minimize"),
  toggleMaximizeWindow: () => ipcRenderer.invoke("window:toggle-maximize"),
  closeWindow: () => ipcRenderer.invoke("window:close")
});
