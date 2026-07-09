const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.join(__dirname, "..");
const pythonRoot = path.join(root, "python");
const isWin = process.platform === "win32";
const mode = process.argv[2] || "all";

function bin(name) {
  return path.join(root, "node_modules", ".bin", isWin ? `${name}.cmd` : name);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd || root,
    stdio: "inherit",
    shell: isWin
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function rm(target) {
  fs.rmSync(target, { force: true, recursive: true });
}

function buildBackend() {
  run("uv", ["sync", "--dev"], { cwd: pythonRoot });
  fs.mkdirSync(path.join(root, "resources"), { recursive: true });
  rm(path.join(root, "resources", "main.exe"));
  run("uv", [
    "run",
    "python",
    "-m",
    "PyInstaller",
    "--onefile",
    "--console",
    "--name",
    "main",
    "main.py",
    "--noconfirm",
    "--distpath",
    "../resources",
    "--workpath",
    "../build/backend",
    "--specpath",
    "../build"
  ], { cwd: pythonRoot });
  console.log("Built backend resources/main.exe");
}

function buildShell() {
  run(bin("tsc"), ["--noEmit"]);
  run(bin("electron-vite"), ["build"]);
}

function removeElectronZip(cacheDir, fileName) {
  if (!fs.existsSync(cacheDir)) {
    return;
  }
  for (const entry of fs.readdirSync(cacheDir, { withFileTypes: true })) {
    const fullPath = path.join(cacheDir, entry.name);
    if (entry.isDirectory()) {
      removeElectronZip(fullPath, fileName);
    } else if (entry.name === fileName) {
      rm(fullPath);
    }
  }
}

function buildInstaller() {
  rm(path.join(root, "release", "win-unpacked"));
  const electronVersion = require(path.join(root, "package.json")).devDependencies.electron.replace(/^[^0-9]*/, "");
  if (process.env.LOCALAPPDATA) {
    removeElectronZip(
      path.join(process.env.LOCALAPPDATA, "electron", "Cache"),
      `electron-v${electronVersion}-win32-x64.zip`
    );
  }
  run(bin("electron-builder"), ["--win", "--publish", "never"]);
  run(process.execPath, [path.join(root, "scripts", "write_release_notes.js")]);
}

const steps = {
  backend: buildBackend,
  shell: buildShell,
  installer: buildInstaller
};

if (mode === "all") {
  buildBackend();
  buildShell();
  buildInstaller();
} else if (steps[mode]) {
  steps[mode]();
} else {
  console.error(`Unknown build target: ${mode}`);
  process.exit(1);
}
