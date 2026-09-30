import fs from "node:fs";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "../..");
const frontendRoot = path.join(projectRoot, "frontend");
const lock = JSON.parse(fs.readFileSync(path.join(frontendRoot, "package-lock.json"), "utf8"));
const outputPath = path.join(projectRoot, "THIRD_PARTY_LICENSES", "FRONTEND_DEPENDENCIES.txt");

function repositoryUrl(repository, fallback) {
  const raw = (typeof repository === "string" ? repository : repository?.url) ?? fallback;
  if (!raw) return "UNKNOWN";
  const normalized = raw
    .replace(/^git\+/, "")
    .replace(/^git:\/\/github\.com\//, "https://github.com/")
    .replace(/^github:/, "https://github.com/")
    .replace(/\.git$/, "");
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(normalized)
    ? `https://github.com/${normalized}`
    : normalized;
}

const records = [];
for (const [relativePath, locked] of Object.entries(lock.packages)) {
  if (!relativePath.startsWith("node_modules/") || locked.dev) continue;

  const installedPath = path.join(frontendRoot, relativePath);
  const manifest = JSON.parse(fs.readFileSync(path.join(installedPath, "package.json"), "utf8"));
  const noticeNames = fs
    .readdirSync(installedPath, { withFileTypes: true })
    .filter(
      (entry) =>
        entry.isFile() &&
        /^(licen[cs]e|copying|notice|authors?|copyright)([.-].*)?$/i.test(entry.name),
    )
    .map((entry) => entry.name)
    .sort();
  if (!noticeNames.length) {
    throw new Error(`No license or notice file found for ${manifest.name}@${manifest.version}`);
  }

  records.push({
    name: manifest.name,
    version: manifest.version,
    license: manifest.license ?? locked.license ?? "UNKNOWN",
    repository: repositoryUrl(manifest.repository, locked.resolved),
    sourceArchive: locked.resolved,
    texts: noticeNames.map((name) => ({
      name,
      text: fs.readFileSync(path.join(installedPath, name), "utf8").trim(),
    })),
  });
}

records.sort((left, right) => left.name.localeCompare(right.name) || left.version.localeCompare(right.version));
const rendered = [
  "AQA Frontend Runtime Dependencies",
  "===========================================",
  "",
  "Generated from frontend/package-lock.json production entries and the exact installed package license files.",
  "This is a conservative inventory: type-only or peer packages may be listed even when Vite removes their code.",
  "Developer-only packages are excluded.",
  "",
  ...records.flatMap((record) => [
    `${record.name} ${record.version}`,
    `License: ${record.license}`,
    `Exact source archive: ${record.sourceArchive}`,
    `Repository: ${record.repository}`,
    "",
    ...record.texts.flatMap(({ name, text }) => [`[${name}]`, "", text, ""]),
    "",
    "--------------------------------------------------------------------------------",
    "",
  ]),
].join("\n");

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, rendered);
