const KEEP_RELEASES = 3;

function releaseVersion(release) {
  if (release.draft || release.prerelease) {
    return null;
  }
  return /^v?(\d+)\.(\d+)\.(\d+)$/.exec(release.tag_name)?.slice(1).map(Number) || null;
}

function compareVersions(left, right) {
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] - right[index];
    }
  }
  return 0;
}

function hasName(asset, name) {
  return [asset.name, asset.filename, asset.file_name].includes(name);
}

function installerName(release) {
  return `Codex-Forge-Setup-${release.tag_name.replace(/^v/, "")}.exe`;
}

async function pruneReleaseAssets({ currentRelease, listReleases, listAssets, deleteAsset }) {
  const currentVersion = releaseVersion(currentRelease);
  if (!currentVersion) {
    console.log(`Skipping release cleanup for non-stable tag ${currentRelease.tag_name}`);
    return;
  }

  const currentAssets = await listAssets(currentRelease.id);
  for (const name of [installerName(currentRelease), "latest.yml"]) {
    if (!currentAssets.some((asset) => hasName(asset, name))) {
      throw new Error(`Release ${currentRelease.tag_name} is missing ${name}; old assets were not cleaned`);
    }
  }

  const releases = await listReleases();
  const candidates = [];
  for (const release of [{ ...currentRelease, assets: currentAssets }, ...releases.filter((item) => item.id !== currentRelease.id)]) {
    const version = releaseVersion(release);
    if (!version) {
      continue;
    }
    const assets = release.assets || await listAssets(release.id);
    if (assets.some((asset) => hasName(asset, installerName(release)))) {
      candidates.push({ release, version });
    }
  }
  candidates.sort((left, right) => compareVersions(right.version, left.version));

  if (compareVersions(candidates[0].version, currentVersion) > 0) {
    console.log(`Skipping release cleanup when republishing older version ${currentRelease.tag_name}`);
    return;
  }

  console.log(`Keeping installer assets for ${candidates.slice(0, KEEP_RELEASES).map((item) => item.release.tag_name).join(", ")}`);
  for (const { release } of candidates.slice(KEEP_RELEASES)) {
    const assets = await listAssets(release.id);
    for (const asset of assets) {
      const name = [installerName(release), "latest.yml"].find((value) => hasName(asset, value));
      if (name) {
        console.log(`Deleting old release asset ${release.tag_name}/${name}`);
        await deleteAsset(release.id, asset.id);
      }
    }
  }
}

module.exports = { pruneReleaseAssets };
