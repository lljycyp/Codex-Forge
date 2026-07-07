const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const changelogPath = path.join(root, "CHANGELOG.md");
const releaseNotesPath = path.join(root, "release", "release-notes.md");
const latestPath = path.join(root, "release", "latest.yml");

if (!fs.existsSync(latestPath)) {
  process.exit(0);
}

const version = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8")).version;
const changelogLines = fs.readFileSync(changelogPath, "utf8").split(/\r?\n/);
const start = changelogLines.findIndex((line) => line.trim() === `## ${version}`);
const end = changelogLines.findIndex((line, index) => index > start && /^##\s+/.test(line));
const notes = start === -1 ? "" : changelogLines.slice(start + 1, end === -1 ? undefined : end).join("\n").trim();

if (!notes) {
  throw new Error(`CHANGELOG.md missing notes for version ${version}`);
}

const lines = fs.readFileSync(latestPath, "utf8").split(/\r?\n/);
const kept = [];
let skipping = false;

for (const line of lines) {
  if (line.startsWith("releaseNotes:")) {
    skipping = true;
    continue;
  }
  if (skipping && line && !line.startsWith(" ")) {
    skipping = false;
  }
  if (!skipping) {
    kept.push(line);
  }
}

while (kept.length && kept[kept.length - 1] === "") {
  kept.pop();
}

kept.push("releaseNotes: |", ...notes.split("\n").map((line) => `  ${line}`), "");
fs.writeFileSync(latestPath, kept.join("\n"), "utf8");
fs.writeFileSync(releaseNotesPath, `${notes}\n`, "utf8");
