import { mkdir, copyFile } from "node:fs/promises"
import { resolve } from "node:path"
const target = resolve("public/ocr")
await mkdir(target, { recursive: true })
const assets = [
  ["tesseract.js/dist/worker.min.js", "worker.min.js"],
  ["tesseract.js-core/tesseract-core-lstm.wasm.js", "tesseract-core-lstm.wasm.js"],
  ["tesseract.js-core/tesseract-core-simd-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js"],
  ["@tesseract.js-data/eng/4.0.0_best_int/eng.traineddata.gz", "eng.traineddata.gz"],
  ["tesseract.js/LICENSE.md", "tesseract-LICENSE.txt"],
  ["tesseract.js-core/LICENSE", "core-LICENSE.txt"]
]
await Promise.all(assets.map(([src, name]) => copyFile(resolve("node_modules", src), resolve(target, name))))
