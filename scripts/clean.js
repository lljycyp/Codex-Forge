const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");

function rm(target) {
  fs.rmSync(target, { force: true, recursive: true });
}

function cleanGeneratedDirs(directory) {
  if (!fs.existsSync(directory)) {
    return;
  }
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (!entry.isDirectory()) {
      continue;
    }
    if (entry.name === ".venv") {
      continue;
    }
    if (entry.name === "__pycache__" || entry.name.endsWith(".egg-info")) {
      rm(fullPath);
      continue;
    }
    cleanGeneratedDirs(fullPath);
  }
}

for (const name of ["build", "dist", "out", "release", "__pycache__"]) {
  rm(path.join(root, name));
}

rm(path.join(root, "resources", "main.exe"));

for (const entry of fs.readdirSync(root)) {
  if (entry.endsWith(".spec")) {
    rm(path.join(root, entry));
  }
}

cleanGeneratedDirs(path.join(root, "src"));
cleanGeneratedDirs(path.join(root, "python"));

console.log("Cleaned build artifacts.");
