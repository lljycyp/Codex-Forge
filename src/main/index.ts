import { app, BrowserWindow, Menu, Tray, ipcMain, shell } from "electron";
import {
  autoUpdater,
  type ProgressInfo,
  type UpdateDownloadedEvent,
  type UpdateInfo,
} from "electron-updater";
import { join } from "node:path";
import { registerIpcHandlers } from "./ipc";

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let isQuitting = false;
let updateDownloading = false;
let updateDownloaded = false;
let latestUpdateVersion = "";
let latestUpdateReleaseNotes = "";
const gotSingleInstanceLock = app.requestSingleInstanceLock();

type UpdateEvent =
  | {
      status: "available";
      currentVersion: string;
      version: string;
      releaseNotes?: string;
    }
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
  | { status: "not-available"; currentVersion: string; version: string }
  | { status: "error"; message: string };
let lastUpdateEvent: UpdateEvent | null = null;

function getAppIconPath(): string {
  return join(__dirname, "../../assets/app.ico");
}

function showMainWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) {
    createMainWindow();
    return;
  }
  if (mainWindow.isMinimized()) {
    mainWindow.restore();
  }
  mainWindow.show();
  mainWindow.focus();
}

function sendUpdateEvent(event: UpdateEvent): void {
  lastUpdateEvent = event;
  if (!mainWindow || mainWindow.isDestroyed()) {
    return;
  }
  mainWindow.webContents.send("app:update-event", event);
}

function releaseNotesText(info: UpdateInfo): string | undefined {
  if (typeof info.releaseNotes === "string") {
    return info.releaseNotes;
  }
  if (Array.isArray(info.releaseNotes)) {
    return info.releaseNotes
      .map((item) => item.note)
      .filter(Boolean)
      .join("\n");
  }
  return undefined;
}

function registerUpdateHandlers(): void {
  autoUpdater.autoDownload = false;
  // 本地开发模式默认不会检查更新；强制读取 dev-app-update.yml，方便验证真实 GitHub 更新链路。
  autoUpdater.forceDevUpdateConfig = !app.isPackaged;
  // autoUpdater.forceDevUpdateConfig = false
  autoUpdater.on("update-available", (info: UpdateInfo) => {
    latestUpdateVersion = info.version;
    latestUpdateReleaseNotes = releaseNotesText(info) ?? "";
    sendUpdateEvent({
      status: "available",
      currentVersion: app.getVersion(),
      version: info.version,
      releaseNotes: latestUpdateReleaseNotes || undefined,
    });
  });
  autoUpdater.on("download-progress", (info: ProgressInfo) => {
    sendUpdateEvent({
      status: "downloading",
      currentVersion: app.getVersion(),
      version: latestUpdateVersion,
      percent: info.percent,
      transferred: info.transferred,
      total: info.total,
      bytesPerSecond: info.bytesPerSecond,
    });
  });
  autoUpdater.on("update-downloaded", (event: UpdateDownloadedEvent) => {
    updateDownloaded = true;
    updateDownloading = false;
    sendUpdateEvent({
      status: "downloaded",
      currentVersion: app.getVersion(),
      version: event.version,
      releaseNotes: latestUpdateReleaseNotes || undefined,
    });
  });
  autoUpdater.on("update-not-available", (info: UpdateInfo) => {
    latestUpdateReleaseNotes = "";
    sendUpdateEvent({
      status: "not-available",
      currentVersion: app.getVersion(),
      version: info.version,
    });
  });
  autoUpdater.on("error", (error: Error) => {
    updateDownloading = false;
    sendUpdateEvent({ status: "error", message: error.message || "更新失败" });
  });
}

function createMainWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 760,
    minWidth: 980,
    minHeight: 640,
    title: "Codex Forge",
    icon: getAppIconPath(),
    frame: false,
    titleBarStyle: "hidden",
    titleBarOverlay: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.on("close", (event) => {
    if (isQuitting) {
      return;
    }
    event.preventDefault();
    mainWindow?.hide();
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  mainWindow.webContents.once("did-finish-load", () => {
    if (lastUpdateEvent) {
      mainWindow?.webContents.send("app:update-event", lastUpdateEvent);
    }
  });

  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    mainWindow.loadFile(join(__dirname, "../renderer/index.html"));
  }
}

function createTray(): void {
  if (tray) {
    return;
  }
  tray = new Tray(getAppIconPath());
  tray.setToolTip("Codex Forge");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "打开主窗口",
        click: showMainWindow,
      },
      {
        label: "退出",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
  tray.on("click", showMainWindow);
  tray.on("double-click", showMainWindow);
}

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    showMainWindow();
  });

  app.whenReady().then(() => {
    registerIpcHandlers();
    registerUpdateHandlers();
    createMainWindow();
    createTray();
    if (app.isPackaged || autoUpdater.forceDevUpdateConfig) {
      autoUpdater.checkForUpdates().catch((error) => {
        sendUpdateEvent({
          status: "error",
          message: error instanceof Error ? error.message : "检查更新失败",
        });
      });
    }

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createMainWindow();
        return;
      }
      showMainWindow();
    });
  });
}

app.on("before-quit", () => {
  isQuitting = true;
});

app.on("window-all-closed", () => {
  if (process.platform === "darwin") {
    return;
  }
  if (isQuitting) {
    app.quit();
  }
});

ipcMain.handle("app:open-external", (_event, target: string) =>
  shell.openExternal(target),
);
ipcMain.handle("app:update-download", async () => {
  if (updateDownloaded || updateDownloading) {
    return;
  }
  updateDownloading = true;
  await autoUpdater.downloadUpdate();
});
ipcMain.handle("app:update-check", async () => {
  if (updateDownloading) {
    return;
  }
  await autoUpdater.checkForUpdates();
});
ipcMain.handle("app:update-install", () => {
  if (!updateDownloaded) {
    return;
  }
  isQuitting = true;
  autoUpdater.quitAndInstall();
});
