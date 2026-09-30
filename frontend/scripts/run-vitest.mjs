import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

// Node 22 and newer expose localStorage globally and require a backing file.
// Node 20 is also supported by this project but does not recognize this flag.
const nodeMajor = Number.parseInt(process.versions.node.split(".")[0] ?? "", 10);
const localStorageOption =
  nodeMajor >= 22 ? `--localstorage-file=${join(tmpdir(), "aqa-vitest-localstorage")}` : undefined;
// Node 20 has no global navigator. The shared test setup refines its locale
// before jsdom is installed, so provide the minimal host object Node 21+
// exposes and let each configured test environment populate it normally.
const navigatorOption =
  nodeMajor === 20 ? "--import=data:text/javascript,globalThis.navigator%3D%7B%7D" : undefined;
const nodeOptions = [process.env.NODE_OPTIONS, localStorageOption, navigatorOption]
  .filter(Boolean)
  .join(" ");

const result = spawnSync(
  process.execPath,
  ["node_modules/vitest/vitest.mjs", "run", ...process.argv.slice(2)],
  {
    env: { ...process.env, NODE_OPTIONS: nodeOptions },
    stdio: "inherit",
  },
);

if (result.error) throw result.error;
process.exit(result.status ?? 1);
