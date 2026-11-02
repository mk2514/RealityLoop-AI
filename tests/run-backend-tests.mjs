import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";

const root = process.cwd();
const candidates = [
  resolve(root, "backend", ".venv-dev-check", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"),
  resolve(root, "backend", ".venv-dev", process.platform === "win32" ? "Scripts/python.exe" : "bin/python"),
];
const localPython = candidates.find((candidate) => existsSync(candidate));
const command = localPython ?? (process.platform === "win32" ? "py" : "python3");
const launcherArgs = localPython
  ? ["-m", "pytest"]
  : command === "py"
    ? ["-3.12", "-m", "pytest"]
    : ["-m", "pytest"];
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
