// Writes dist/src.sha256: sha256 hex of every ui input of the bundle, so
// test_ui.py can tell a stale bundle. Layout: for each file below in sorted
// POSIX-path order (relative to ui/): <path> NUL <bytes> NUL. Files:
//   src/** and public/** (if present), index.html, package.json,
//   package-lock.json, vite.config.ts, tsconfig*.json (in ui/ only).
// Any file or folder whose name starts with "." is skipped (.DS_Store, swap
// files). Keep in step with dist_stamp() in scripts/test_ui.py.
import { createHash } from "node:crypto"
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const root = import.meta.dirname

const walk = (rel) =>
  readdirSync(join(root, rel), { withFileTypes: true })
    .filter((e) => !e.name.startsWith("."))
    .flatMap((e) =>
      e.isDirectory() ? walk(`${rel}/${e.name}`) : [`${rel}/${e.name}`],
    )

const tsconfigs = readdirSync(root, { withFileTypes: true })
  .filter((e) => e.isFile() && /^tsconfig.*\.json$/.test(e.name))
  .map((e) => e.name)

const files = [
  ...walk("src"),
  ...(existsSync(join(root, "public")) ? walk("public") : []),
  "index.html",
  "package.json",
  "package-lock.json",
  "vite.config.ts",
  ...tsconfigs,
].sort()
const h = createHash("sha256")
for (const f of files) {
  h.update(f)
  h.update("\0")
  h.update(readFileSync(join(root, f)))
  h.update("\0")
}
writeFileSync(join(root, "dist", "src.sha256"), `${h.digest("hex")}\n`)
