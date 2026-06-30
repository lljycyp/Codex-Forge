import { app } from "electron";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

type BackendResult = {
  ok: boolean;
  data: Record<string, unknown>;
  error: string;
};

type BackendCommand = {
  command: string;
  args: string[];
  mode: "packaged" | "development";
};

function getProjectRoot(): string {
  return app.isPackaged ? process.resourcesPath : join(__dirname, "../..");
}

function getPythonRoot(projectRoot: string): string {
  return join(projectRoot, "python");
}

function getBackendCommand(): BackendCommand {
  const packagedBackend = join(process.resourcesPath, "main.exe");
  if (app.isPackaged && existsSync(packagedBackend)) {
    return { command: packagedBackend, args: [], mode: "packaged" };
  }
  const projectRoot = getProjectRoot();
  const pythonCommand = process.platform === "win32"
    ? join(projectRoot, "python", ".venv", "Scripts", "python.exe")
    : join(projectRoot, "python", ".venv", "bin", "python");
  return { command: pythonCommand, args: ["-m", "bridge.cli"], mode: "development" };
}

export function invokeBackend(commandName: string, payload: unknown): Promise<BackendResult> {
  const backend = getBackendCommand();
  const args = [...backend.args, commandName, JSON.stringify(payload ?? {})];
  const projectRoot = getProjectRoot();
  const cwd = backend.mode === "development" ? getPythonRoot(projectRoot) : projectRoot;
  const options = {
    cwd,
    windowsHide: true,
    maxBuffer: 1024 * 1024 * 8
  };

  return new Promise((resolve) => {
    execFile(
      backend.command,
      args,
      options,
      (error, stdout, stderr) => {
        const output = stdout.trim();
        if (output) {
          try {
            resolve(JSON.parse(output) as BackendResult);
            return;
          } catch {
            resolve({ ok: false, data: {}, error: output });
            return;
          }
        }
        const detail = [
          stderr.trim() || error?.message || "后端无响应",
          `命令：${backend.command}`,
          `目录：${cwd}`,
          `模式：${backend.mode}`
        ].join("\n");
        resolve({ ok: false, data: {}, error: detail });
      }
    );
  });
}
