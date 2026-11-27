import { openDB, type DBSchema } from "idb"
import samples from "./samples.json"
import { type Changes, type Library, type Page, maxAttempts } from "./types"
interface Store extends DBSchema {
  pages: { key: string; value: Page }
  images: { key: string; value: Blob }
  meta: { key: string; value: boolean }
}
const db = () => openDB<Store>("document-library-v1", 1, { upgrade(database) {
  database.createObjectStore("pages", { keyPath: "id" })
  database.createObjectStore("images")
  database.createObjectStore("meta")
} })
let connection: ReturnType<typeof db> | undefined
const database = () => connection ??= db()
async function init() {
  const tx = (await database()).transaction(["pages", "meta"], "readwrite")
  if (!await tx.objectStore("meta").get("initialized")) {
    for (const page of samples) await tx.objectStore("pages").add(page as Page)
    await tx.objectStore("meta").put(true, "initialized")
  }
  await tx.done
}
let initialized: Promise<void> | undefined
async function change(id: string, apply: (current: Page) => Page) {
  const tx = (await database()).transaction("pages", "readwrite")
  const current = await tx.store.get(id)
  if (current) await tx.store.put(apply(current))
  await tx.done
}
export const local: Library = {
  async list(query = "") {
    await (initialized ??= init())
    const needle = query.trim().toLowerCase()
    return (await (await database()).getAll("pages")).filter(p =>
      p.title.toLowerCase().includes(needle) || p.text.toLowerCase().includes(needle))
  },
  async upload(file, title) {
    const page: Page = { id: crypto.randomUUID(), title, filename: file.name, mime: file.type,
      createdAt: new Date().toISOString(), status: "queued", attempts: 0, text: "", starred: false }
    const tx = (await database()).transaction(["pages","images"], "readwrite")
    await tx.objectStore("images").put(file, page.id)
    await tx.objectStore("pages").add(page)
    await tx.done
    return page
  },
  async update(id, changes: Changes) {
    await change(id, p => ({...p, ...changes, status: changes.text !== undefined ? "reviewed" : p.status}))
  },
  async remove(id) {
    const tx = (await database()).transaction(["pages","images"], "readwrite")
    await tx.objectStore("pages").delete(id)
    await tx.objectStore("images").delete(id)
    await tx.done
  },
  async image(page) {
    if (page.imageUrl) return page.imageUrl
    const blob = await (await database()).get("images", page.id)
    if (!blob) throw new Error("The saved image could not be opened.")
    return blob
  },
  async retry(id) {
    await change(id, p => p.status === "failed" && p.attempts < maxAttempts ? {...p, status: "queued", error: undefined} : p)
  },
}
export async function processQueue(refresh: () => void) {
  // The lock is released if the tab closes. A new holder can resume an interrupted page.
  await navigator.locks.request("document-library-ocr", { ifAvailable: true }, async lock => {
    if (!lock) return
    while (true) {
      const pages = await local.list()
      const page = pages.filter(p => p.status === "queued" || p.status === "processing")
        .sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0]
      if (!page) return
      if (page.attempts >= maxAttempts) {
        await change(page.id, p => ({...p, status: "failed", error: "Processing was interrupted too many times. Upload a clearer scan."}))
        refresh()
        continue
      }
      await change(page.id, p => ({...p, status: "processing", attempts: p.attempts + 1}))
      refresh()
      try {
        const { recognize } = await import("./recognize")
        const text = await recognize(await local.image(page))
        await change(page.id, p => ({...p, text, status: "ready"}))
      } catch {
        await change(page.id, p => ({...p, status: "failed", error: "Text extraction failed. Retry the scan or upload a clearer image."}))
      }
      refresh()
    }
  })
}
