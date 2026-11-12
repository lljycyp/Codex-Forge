const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { pruneReleaseAssets } = require("../release_retention");

function makeRelease(id, version) {
  return {
    id,
    tag_name: `v${version}`,
    assets: [
      { id: id * 10, name: `Codex-Forge-Setup-${version}.exe` },
      { id: id * 10 + 1, name: "latest.yml" },
      { id: id * 10 + 2, name: "manual.pdf" },
    ],
  };
}

function fixture(releases) {
  const assets = new Map(releases.map((release) => [release.id, release.assets]));
  const deleted = [];
  return {
    currentRelease: releases[0],
    listReleases: async () => releases,
    listAssets: async (id) => assets.get(id),
    deleteAsset: async (...ids) => deleted.push(ids),
    deleted,
  };
}

test("keeps the three newest numeric versions and deletes only managed assets", async () => {
  const store = fixture([
    makeRelease(12, "1.0.12"), makeRelease(9, "1.0.9"), makeRelease(11, "1.0.11"),
    makeRelease(8, "1.0.8"), makeRelease(10, "1.0.10"),
  ]);
  await pruneReleaseAssets(store);
  assert.deepEqual(store.deleted, [[9, 90], [9, 91], [8, 80], [8, 81]]);
});

test("fewer than three installer versions need no cleanup", async () => {
  const store = fixture([makeRelease(2, "1.0.2"), makeRelease(1, "1.0.1")]);
  await pruneReleaseAssets(store);
  assert.deepEqual(store.deleted, []);
});

test("drafts, prereleases, custom tags, and empty releases do not displace usable installers", async () => {
  const store = fixture([
    makeRelease(4, "1.0.4"),
    { ...makeRelease(8, "1.0.8"), draft: true },
    { ...makeRelease(7, "1.0.7"), prerelease: true },
    { ...makeRelease(6, "1.0.6"), tag_name: "preview" },
    { ...makeRelease(5, "1.0.5"), assets: [] },
    makeRelease(3, "1.0.3"), makeRelease(2, "1.0.2"), makeRelease(1, "1.0.1"),
  ]);
  await pruneReleaseAssets(store);
  assert.deepEqual(store.deleted, [[1, 10], [1, 11]]);
});

test("republishing an older version does not clean up any releases", async () => {
  const store = fixture([
    makeRelease(1, "1.0.1"), makeRelease(5, "1.0.5"), makeRelease(4, "1.0.4"),
    makeRelease(3, "1.0.3"), makeRelease(2, "1.0.2"),
  ]);
  await pruneReleaseAssets(store);
  assert.deepEqual(store.deleted, []);
});

for (const missing of ["installer", "manifest"]) {
  test(`a missing current ${missing} stops cleanup before listing old releases`, async () => {
    const current = makeRelease(4, "1.0.4");
    current.assets.splice(missing === "installer" ? 0 : 1, 1);
    const store = fixture([current, makeRelease(1, "1.0.1")]);
    store.listReleases = async () => assert.fail("Old releases must not be read");
    await assert.rejects(pruneReleaseAssets(store), /is missing/);
    assert.deepEqual(store.deleted, []);
  });
}

test("Gitee filename aliases and releases without embedded assets are supported", async () => {
  const releases = [4, 3, 2, 1].map((id) => makeRelease(id, `1.0.${id}`));
  for (const release of releases) {
    release.assets = release.assets.map((asset, index) => ({ id: asset.id, [index ? "file_name" : "filename"]: asset.name }));
  }
  const store = fixture(releases);
  delete releases[3].assets;
  await pruneReleaseAssets(store);
  assert.deepEqual(store.deleted, [[1, 10], [1, 11]]);
});

test("an inventory API failure prevents deletion", async () => {
  const store = fixture([4, 3, 2, 1].map((id) => makeRelease(id, `1.0.${id}`)));
  store.listReleases = async () => { throw new Error("API unavailable"); };
  await assert.rejects(pruneReleaseAssets(store), /API unavailable/);
  assert.deepEqual(store.deleted, []);
});

async function runPublisher(provider, { failUploadAt = 0, dryRun = false, missingManifest = false } = {}) {
  const releases = [4, 3, 2, 1, 0].map((version) => makeRelease(version + 1, `1.0.${version}`));
  const current = releases[0];
  current.assets = [];
  const assets = new Map(releases.map((release) => [release.id, [...release.assets]]));
  const requests = [];
  const events = [];
  let uploadCount = 0;
  const response = (data, status = 200) => ({ ok: status < 400, status, text: async () => JSON.stringify(data) });

  function upload(name) {
    uploadCount += 1;
    if (uploadCount === failUploadAt) {
      return false;
    }
    events.push({ type: "upload", name });
    if (!(missingManifest && name === "latest.yml")) {
      assets.get(current.id).push({ id: 100 + uploadCount, name });
    }
    return true;
  }

  async function fetchFixture(input, options = {}) {
    const url = new URL(input);
    const method = options.method || "GET";
    requests.push({ path: url.pathname, method, page: url.searchParams.get("page") });
    if (url.hostname === "uploads.github.com") {
      return response({}, upload(url.searchParams.get("name")) ? 201 : 500);
    }
    if (url.pathname.includes("/releases/tags/") || method === "PATCH") {
      return response(current);
    }
    if (method === "DELETE") {
      assert.match(url.pathname, /\/(?:assets|attach_files)\/\d+$/);
      events.push({ type: "delete", id: Number(url.pathname.split("/").at(-1)) });
      return response(null);
    }
    const assetList = url.pathname.match(/\/releases\/(\d+)\/(?:assets|attach_files)$/);
    if (assetList) {
      return response(assets.get(Number(assetList[1])));
    }
    if (url.pathname.endsWith("/releases")) {
      assert.equal(url.searchParams.get("per_page"), "100");
      const pages = [
        [...releases.slice(0, 4), ...Array.from({ length: 96 }, (_, index) => ({ id: 1000 + index, tag_name: "draft", draft: true }))],
        [releases[4]],
      ];
      return response(pages[Number(url.searchParams.get("page")) - 1]);
    }
    assert.fail(`Unexpected request: ${method} ${url.pathname}`);
  }

  const sourcePath = path.join(__dirname, `../publish_${provider}_release.js`);
  const source = fs.readFileSync(sourcePath, "utf8");
  const fakeFs = {
    existsSync: () => true,
    statSync: () => ({ isDirectory: () => false, size: 8 }),
    readFileSync: (file) => path.basename(file) === "package.json" ? JSON.stringify({ version: "1.0.4" }) : "Release notes",
    createReadStream: () => Buffer.from("fixture"),
  };
  const fakeProcess = {
    platform: "win32",
    env: { GITHUB_TOKEN: "fixture", GITEE_TOKEN: "fixture", [`${provider.toUpperCase()}_DRY_RUN`]: dryRun ? "1" : "0" },
    exit: (code) => { throw new Error(`Exit ${code}`); },
  };
  let error;
  try {
    await vm.runInNewContext(source, {
      __dirname: path.dirname(sourcePath),
      process: fakeProcess,
      console: { log() {}, error() {} },
      URL,
      URLSearchParams,
      AbortSignal,
      fetch: fetchFixture,
      require: (name) => {
        if (name === "node:fs") return fakeFs;
        if (name === "node:path") return path;
        if (name === "./release_retention") return { pruneReleaseAssets };
        if (name === "node:child_process") {
          return { spawnSync: (_command, args) => ({ status: upload(args.find((arg) => arg.startsWith("file=@")).split(";filename=")[1]) ? 0 : 22, stdout: "fixture" }) };
        }
        assert.fail(`Unexpected import: ${name}`);
      },
    });
  } catch (caught) {
    error = caught;
  }
  return { error, events, requests };
}

for (const provider of ["github", "gitee"]) {
  test(`${provider}: uploads both files before cleanup and finds older releases on later pages`, async () => {
    const result = await runPublisher(provider);
    assert.ifError(result.error);
    assert.deepEqual(result.events.slice(0, 2), [
      { type: "upload", name: "Codex-Forge-Setup-1.0.4.exe" }, { type: "upload", name: "latest.yml" },
    ]);
    assert.deepEqual(result.events.slice(2).map((event) => event.id), [20, 21, 10, 11]);
    assert.ok(result.requests.some((request) => request.page === "2"));
  });

  for (const failUploadAt of [1, 2]) {
    test(`${provider}: upload failure ${failUploadAt} leaves old versions untouched`, async () => {
      const result = await runPublisher(provider, { failUploadAt });
      assert.match(result.error?.message || "", /Exit 1/);
      assert.ok(result.events.every((event) => event.type === "upload"));
      assert.ok(result.requests.every((request) => !request.path.endsWith("/releases")));
    });
  }

  test(`${provider}: missing uploaded manifest prevents cleanup`, async () => {
    const result = await runPublisher(provider, { missingManifest: true });
    assert.match(result.error?.message || "", /Exit 1/);
    assert.ok(result.events.every((event) => event.type === "upload"));
  });

  test(`${provider}: dry run makes no remote requests or deletions`, async () => {
    const result = await runPublisher(provider, { dryRun: true });
    assert.ifError(result.error);
    assert.deepEqual(result.requests, []);
    assert.deepEqual(result.events, []);
  });
}
