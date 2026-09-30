import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const frontendDirectory = resolve(scriptDirectory, "..");
const schemaPath = resolve(frontendDirectory, "../openapi/openapi.json");
const outputPath = resolve(frontendDirectory, "src/api/generated.ts");
const check = process.argv.includes("--check");

const nodes = await openapiTS(pathToFileURL(schemaPath));
const generated = astToString(nodes);

if (check) {
  let existing;
  try {
    existing = await readFile(outputPath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") {
      console.error(`Generated API types are missing: ${outputPath}`);
      process.exit(1);
    }
    throw error;
  }
  if (existing !== generated) {
    console.error("Generated API types are stale. Run `npm run api:generate` in frontend/.");
    process.exit(1);
  }
  console.log(`Generated API types are current: ${outputPath}`);
} else {
  await writeFile(outputPath, generated, "utf8");
  console.log(`Wrote generated API types: ${outputPath}`);
}
