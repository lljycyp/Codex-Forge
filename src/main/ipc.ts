import { BrowserWindow, dialog, ipcMain, type OpenDialogOptions } from "electron";
import { invokeBackend } from "./python/launcherBackend";

export function registerIpcHandlers(): void {
  ipcMain.handle("launcher:invoke", async (_event, command: string, payload: unknown) => {
    return invokeBackend(command, payload);
  });
  ipcMain.handle("launcher:select-directory", async (event, defaultPath?: string) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    const options: OpenDialogOptions = {
      title: "选择 CodexProfiles 的存放位置",
      defaultPath,
      properties: ["openDirectory", "createDirectory"]
    };
    const result = window ? await dialog.showOpenDialog(window, options) : await dialog.showOpenDialog(options);
    return result.canceled ? "" : result.filePaths[0] ?? "";
  });
  ipcMain.handle("window:minimize", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize();
  });
  ipcMain.handle("window:toggle-maximize", (event) => {
    const window = BrowserWindow.fromWebContents(event.sender);
    if (!window) {
      return;
    }
    if (window.isMaximized()) {
      window.unmaximize();
      return;
    }
    window.maximize();
  });
  ipcMain.handle("window:close", (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
  });
}
