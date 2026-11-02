import { cp, mkdir, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = resolve(frontendRoot, "..");
const landingDirectory = resolve(repositoryRoot, "dist");
const applicationDirectory = resolve(frontendRoot, "dist");
const outputDirectory = resolve(frontendRoot, "vercel-output");

await rm(outputDirectory, { recursive: true, force: true });
await mkdir(outputDirectory, { recursive: true });
await cp(landingDirectory, outputDirectory, { recursive: true });
await cp(applicationDirectory, resolve(outputDirectory, "app"), {
  recursive: true,
});
