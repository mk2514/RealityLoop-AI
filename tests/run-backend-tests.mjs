import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = process.cwd();
const localPython = resolve(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const command = existsSync(localPython)
  ? localPython
  : process.platform === "win32"
    ? "py"
    : "python3";
const launcherArgs =
  command === "py" ? ["-3", "-m", "pytest"] : ["-m", "pytest"];
const result = spawnSync(
  command,
  [...launcherArgs, "-c", "backend/pyproject.toml", "backend/tests"],
  { cwd: root, stdio: "inherit" },
);

if (result.error) {
  console.error(`Unable to start backend tests: ${result.error.message}`);
  process.exitCode = 1;
} else {
  process.exitCode = result.status ?? 1;
}
