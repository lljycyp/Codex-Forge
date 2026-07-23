import { app, nativeImage } from "electron";
import { randomUUID } from "node:crypto";
import { copyFile, mkdir, readFile, realpath, stat, unlink, writeFile } from "node:fs/promises";
import { basename, extname, join, parse } from "node:path";

export type CodexSkinThemeSummary = {
  id: string;
  name: string;
  builtIn: boolean;
  previewDataUrl: string;
  focusX: number;
  focusY: number;
  safeArea: "left" | "right" | "center" | "none";
  appearance: "auto" | "light" | "dark";
};

export type CodexSkinThemePayload = {
  id: string;
  name: string;
  imageDataUrl: string;
  focusX: number;
  focusY: number;
  safeArea: "left" | "right" | "center" | "none";
  appearance: "auto" | "light" | "dark";
};

export type CodexSkinThemeOptions = Pick<
  CodexSkinThemePayload,
  "focusX" | "focusY" | "safeArea" | "appearance"
>;

export type CodexSkinThemeState = {
  activeThemeId: string;
  paused: boolean;
  themes: CodexSkinThemeSummary[];
};

type CustomThemeRecord = {
  id: string;
  name: string;
  fileName: string;
  mimeType: string;
};

type StoredState = {
  schemaVersion: 1;
  activeThemeId: string;
  paused: boolean;
  themes: CustomThemeRecord[];
  themeOptions: Record<string, CodexSkinThemeOptions>;
};

const builtInThemeId = "builtin-aurora";
const maxImageBytes = 16 * 1024 * 1024;
const maxImageDimension = 16384;
const maxImagePixels = 50_000_000;
const supportedTypes = new Map([
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".webp", "image/webp"],
]);
const defaultThemeOptions: CodexSkinThemeOptions = {
  focusX: 50,
  focusY: 50,
  safeArea: "left",
  appearance: "auto",
};

function rootPath(): string {
  return join(app.getPath("userData"), "codex-skins");
}

function themesPath(): string {
  return join(rootPath(), "themes");
}

function statePath(): string {
  return join(rootPath(), "state.json");
}

function defaultState(): StoredState {
  return {
    schemaVersion: 1,
    activeThemeId: builtInThemeId,
    paused: false,
    themes: [],
    themeOptions: { [builtInThemeId]: { ...defaultThemeOptions } },
  };
}

async function loadState(): Promise<StoredState> {
  await mkdir(themesPath(), { recursive: true });
  try {
    const parsed = JSON.parse(await readFile(statePath(), "utf8")) as Partial<StoredState>;
    const themes = Array.isArray(parsed.themes)
      ? parsed.themes.filter((theme): theme is CustomThemeRecord =>
        Boolean(theme)
        && typeof theme.id === "string"
        && /^[a-f0-9-]{36}$/.test(theme.id)
        && typeof theme.name === "string"
        && typeof theme.fileName === "string"
        && basename(theme.fileName) === theme.fileName
        && typeof theme.mimeType === "string"
      )
      : [];
    const themeIds = new Set([builtInThemeId, ...themes.map((theme) => theme.id)]);
    const rawOptions = parsed.themeOptions && typeof parsed.themeOptions === "object" ? parsed.themeOptions : {};
    const themeOptions = Object.fromEntries(
      [...themeIds].map((themeId) => [themeId, normalizeThemeOptions(rawOptions[themeId])]),
    );
    return {
      schemaVersion: 1,
      activeThemeId: typeof parsed.activeThemeId === "string" && themeIds.has(parsed.activeThemeId)
        ? parsed.activeThemeId
        : builtInThemeId,
      paused: parsed.paused === true,
      themes,
      themeOptions,
    };
  } catch {
    return defaultState();
  }
}

function normalizeThemeOptions(value: Partial<CodexSkinThemeOptions> | undefined): CodexSkinThemeOptions {
  const safeAreas = new Set(["left", "right", "center", "none"]);
  const appearances = new Set(["auto", "light", "dark"]);
  const focusX = Number(value?.focusX);
  const focusY = Number(value?.focusY);
  return {
    focusX: Number.isFinite(focusX) ? Math.max(0, Math.min(100, focusX)) : defaultThemeOptions.focusX,
    focusY: Number.isFinite(focusY) ? Math.max(0, Math.min(100, focusY)) : defaultThemeOptions.focusY,
    safeArea: safeAreas.has(String(value?.safeArea))
      ? value?.safeArea as CodexSkinThemeOptions["safeArea"]
      : defaultThemeOptions.safeArea,
    appearance: appearances.has(String(value?.appearance))
      ? value?.appearance as CodexSkinThemeOptions["appearance"]
      : defaultThemeOptions.appearance,
  };
}

async function saveState(state: StoredState): Promise<void> {
  await mkdir(rootPath(), { recursive: true });
  await writeFile(statePath(), `${JSON.stringify(state, null, 2)}\n`, "utf8");
}

async function previewFor(record: CustomThemeRecord): Promise<string> {
  try {
    const preview = await nativeImage.createThumbnailFromPath(
      join(themesPath(), record.fileName),
      { width: 320, height: 180 },
    );
    return preview.isEmpty() ? "" : preview.toDataURL();
  } catch {
    return "";
  }
}

export async function getCodexSkinThemeState(): Promise<CodexSkinThemeState> {
  const state = await loadState();
  const previews = await Promise.all(state.themes.map(previewFor));
  return {
    activeThemeId: state.activeThemeId,
    paused: state.paused,
    themes: [
      {
        id: builtInThemeId,
        name: "Forge Aurora",
        builtIn: true,
        previewDataUrl: "",
        ...state.themeOptions[builtInThemeId],
      },
      ...state.themes.map((theme, index) => ({
        id: theme.id,
        name: theme.name,
        builtIn: false,
        previewDataUrl: previews[index],
        ...state.themeOptions[theme.id],
      })),
    ],
  };
}

export async function getActiveCodexSkinTheme(): Promise<CodexSkinThemePayload> {
  const state = await loadState();
  const record = state.themes.find((theme) => theme.id === state.activeThemeId);
  if (!record) {
    return {
      id: builtInThemeId,
      name: "Forge Aurora",
      imageDataUrl: "",
      ...state.themeOptions[builtInThemeId],
    };
  }
  try {
    const bytes = await readFile(join(themesPath(), record.fileName));
    return {
      id: record.id,
      name: record.name,
      imageDataUrl: `data:${record.mimeType};base64,${bytes.toString("base64")}`,
      ...state.themeOptions[record.id],
    };
  } catch {
    state.activeThemeId = builtInThemeId;
    await saveState(state);
    return {
      id: builtInThemeId,
      name: "Forge Aurora",
      imageDataUrl: "",
      ...state.themeOptions[builtInThemeId],
    };
  }
}

export async function importCodexSkinTheme(sourcePath: string): Promise<CodexSkinThemeState> {
  const resolvedSource = await realpath(sourcePath);
  const sourceStat = await stat(resolvedSource);
  if (!sourceStat.isFile() || sourceStat.size <= 0 || sourceStat.size > maxImageBytes) {
    throw new Error("背景图必须是小于 16 MB 的普通图片文件");
  }
  const extension = extname(resolvedSource).toLowerCase();
  const mimeType = supportedTypes.get(extension);
  if (!mimeType) {
    throw new Error("仅支持 PNG、JPEG 和 WebP 图片");
  }
  const image = nativeImage.createFromPath(resolvedSource);
  if (image.isEmpty()) {
    throw new Error("无法读取所选背景图");
  }
  const size = image.getSize();
  if (
    size.width <= 0
    || size.height <= 0
    || size.width > maxImageDimension
    || size.height > maxImageDimension
    || size.width * size.height > maxImagePixels
  ) {
    throw new Error("背景图尺寸不能超过 16384 像素或 5000 万总像素");
  }

  const state = await loadState();
  const id = randomUUID();
  const fileName = `${id}${extension === ".jpeg" ? ".jpg" : extension}`;
  const rawName = parse(resolvedSource).name.trim().replace(/[\u0000-\u001f]/g, "");
  const name = (rawName || "自定义主题").slice(0, 48);
  await copyFile(resolvedSource, join(themesPath(), fileName));
  state.themes.push({ id, name, fileName, mimeType });
  state.themeOptions[id] = { ...defaultThemeOptions };
  state.activeThemeId = id;
  state.paused = false;
  await saveState(state);
  return getCodexSkinThemeState();
}

export async function setActiveCodexSkinTheme(themeId: string): Promise<CodexSkinThemeState> {
  const state = await loadState();
  if (themeId !== builtInThemeId && !state.themes.some((theme) => theme.id === themeId)) {
    throw new Error("主题不存在");
  }
  state.activeThemeId = themeId;
  state.paused = false;
  await saveState(state);
  return getCodexSkinThemeState();
}

export async function deleteCodexSkinTheme(themeId: string): Promise<CodexSkinThemeState> {
  if (themeId === builtInThemeId) {
    throw new Error("内置主题不能删除");
  }
  const state = await loadState();
  const index = state.themes.findIndex((theme) => theme.id === themeId);
  if (index < 0) {
    throw new Error("主题不存在");
  }
  const [removed] = state.themes.splice(index, 1);
  delete state.themeOptions[themeId];
  await unlink(join(themesPath(), removed.fileName)).catch(() => undefined);
  if (state.activeThemeId === themeId) {
    state.activeThemeId = builtInThemeId;
  }
  await saveState(state);
  return getCodexSkinThemeState();
}

export async function setCodexSkinPaused(paused: boolean): Promise<CodexSkinThemeState> {
  const state = await loadState();
  state.paused = paused;
  await saveState(state);
  return getCodexSkinThemeState();
}

export async function updateCodexSkinThemeOptions(
  themeId: string,
  options: Partial<CodexSkinThemeOptions>,
): Promise<CodexSkinThemeState> {
  const state = await loadState();
  if (themeId !== builtInThemeId && !state.themes.some((theme) => theme.id === themeId)) {
    throw new Error("主题不存在");
  }
  state.themeOptions[themeId] = normalizeThemeOptions(options);
  state.activeThemeId = themeId;
  state.paused = false;
  await saveState(state);
  return getCodexSkinThemeState();
}
