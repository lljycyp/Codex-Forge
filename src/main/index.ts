import { app, BrowserWindow, ipcMain, shell } from "electron";
import { join } from "node:path";
import { registerIpcHandlers } from "./ipc";

function createMainWindow(): void {
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 980,
    minHeight: 640,
    title: "Codex 多账号启动器",
    icon: join(__dirname, "../../assets/app.ico"),
    frame: false,
    titleBarStyle: "hidden",
    titleBarOverlay: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false
    }
  });

  if (process.env.ELECTRON_RENDERER_URL) {
    window.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    window.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

app.whenReady().then(() => {
  registerIpcHandlers();
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

ipcMain.handle("app:open-external", (_event, target: string) => shell.openExternal(target));
