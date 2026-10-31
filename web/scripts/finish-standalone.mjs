// Rename the single-file build to LogicLens.html and check it really is self-contained.
import fs from 'node:fs'
import path from 'node:path'

const dir = path.resolve('standalone')
const src = path.join(dir, 'index.html')
const out = path.join(dir, 'LogicLens.html')
const html = fs.readFileSync(src, 'utf8')
const external = [...html.matchAll(/(?:src|href)="(?!data:|#|https?:\/\/)([^"]+)"/g)].map((m) => m[1])
if (external.length) {
  console.error('standalone build still references files:', external)
  process.exit(1)
}
fs.renameSync(src, out)
console.log(`standalone/LogicLens.html  ${(html.length / 1024 / 1024).toFixed(2)} MB, self-contained`)
