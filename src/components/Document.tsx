import { useEffect, useState } from "react"
import { Check, CircleAlert, CircleCheck, Clock3, FileImage, LoaderCircle, ScanText, Star } from "lucide-react"
import { Badge } from "./ui/badge"
import { Button } from "./ui/button"
import { library } from "@/lib/library"
import { apiBase } from "@/lib/api"
import { statuses, type Page } from "@/lib/types"
export function StatusBadge({ page }: { page: Page }) {
  const Icon = { ready: ScanText, reviewed: CircleCheck, queued: Clock3, processing: LoaderCircle, failed: CircleAlert }[page.status]
  return <Badge variant="outline" className={'status status-' + page.status}><Icon className={page.status === "processing" ? "spin" : ""}/>{statuses[page.status]}</Badge>
}
export function pageDate(page: Page) { return new Date(page.createdAt).toLocaleDateString("en-US", {month:"short",day:"numeric",year:"numeric"}) }
export function pageType(page: Page) { return page.mime === "image/png" ? "PNG" : "JPG" }
export function ImageView({ page, cover = false }: {page: Page; cover?: boolean}) {
  const url = !apiBase && (cover && page.coverUrl || page.imageUrl)
  const [src, setSrc] = useState<string | undefined>(url || undefined)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let live = true, objectUrl: string | undefined
    setSrc(url || undefined); setFailed(false)
    if (!url) library.image(page).then(data => {
      if (!live) return
      setSrc(typeof data === "string" ? data : (objectUrl = URL.createObjectURL(data)))
    }).catch(() => { if (live) setFailed(true) })
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [page.id, url])
  return failed ? <span className="image-fallback"><FileImage/>Image unavailable</span> : src ? <img src={src} alt={cover ? "" : "Original scan of " + page.title} onError={() => setFailed(true)} /> : <LoaderCircle className="spin"/>
}
export function Highlight({text, query}: {text: string; query: string}) {
  const needle = query.trim()
  const parts = []
  let offset = 0, index: number
  const lower = text.toLowerCase()
  if (!needle) return <>{text}</>
  while ((index = lower.indexOf(needle.toLowerCase(), offset)) !== -1) {
    parts.push(text.slice(offset, index), <mark key={index}>{text.slice(index,index + needle.length)}</mark>)
    offset = index + needle.length
  }
  return <>{parts}{text.slice(offset)}</>
}
function snippet(text: string, query: string) {
  const index = text.toLowerCase().indexOf(query.trim().toLowerCase())
  if (index < 0) return ""
  const start = Math.max(0,index-34), end = Math.min(text.length,index+query.length+48)
  return (start ? "…" : "") + text.slice(start,end).replace(/\s+/g," ") + (end < text.length ? "…" : "")
}
export function DocumentCard({page, query, open, star}: {page: Page; query: string; open: () => void; star: () => void}) {
  const excerpt = query.trim() && snippet(page.text,query)
  return <article className="document-card">
    <button className="card-open" onClick={open} aria-label={'Open '+page.title}>
      <div className="card-cover"><ImageView page={page} cover /></div>
      <div className="card-content">
        <div className="file-meta"><FileImage/> {pageType(page)} <span>·</span> {pageDate(page)}</div>
        <h3><Highlight text={page.title} query={query}/></h3>
        {excerpt && <p className="excerpt"><Highlight text={excerpt} query={query}/></p>}
        <StatusBadge page={page}/>
      </div>
    </button>
    <Button variant="ghost" size="icon" className={'star-button '+(page.starred?'is-starred':'')} aria-label={(page.starred?'Unstar ':'Star ')+page.title} aria-pressed={page.starred} onClick={star}><Star fill={page.starred?'currentColor':'none'}/></Button>
  </article>
}
export function ChoiceMark({ active }: {active: boolean}) { return active ? <Check size={15}/> : <span className="w-[15px]"/> }
