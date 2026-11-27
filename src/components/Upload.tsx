import { useEffect, useRef, useState, type FormEvent } from "react"
import { FileImage, LoaderCircle, UploadCloud, X } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "./ui/dialog"
import { Input } from "./ui/input"
import { Button } from "./ui/button"
import { errorText, type Page } from "@/lib/types"
import { library } from "@/lib/library"
export function Upload({ close, added }: { close: () => void; added: (page: Page) => void }) {
  const [file,setFile] = useState<File | null>(null), [title,setTitle] = useState("")
  const [error,setError] = useState(""), [busy,setBusy] = useState(false), [drag,setDrag] = useState(false)
  const [preview,setPreview] = useState(""), input = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (!file) { setPreview(""); return }
    const url = URL.createObjectURL(file); setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])
  function choose(files: FileList | null) {
    if (!files?.length) return
    if (files.length !== 1) { setError("Choose one page per upload."); return }
    const image = files[0]
    if (!["image/jpeg","image/png"].includes(image.type) || image.size === 0) { setError("Choose a non-empty JPG or PNG image."); return }
    if (image.size > 10*1024*1024) { setError("Choose an image smaller than 10 MB."); return }
    setFile(image); setError(""); setTitle(image.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g," ").slice(0,160))
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!file || !title.trim() || busy) return
    setBusy(true)
    try { const page = await library.upload(file,title.trim()); added(page) }
    catch(e) { setError(errorText(e)); setBusy(false) }
  }
  return <Dialog open onOpenChange={v => { if (!v && !busy) close() }}>
    <DialogContent><DialogHeader><DialogTitle>Upload a page</DialogTitle><DialogDescription>Choose a scan or photo of one printed English page.</DialogDescription></DialogHeader>
    <form onSubmit={submit} className="form-stack">
      <input hidden ref={input} aria-label="Choose image" type="file" accept="image/jpeg,image/png" onChange={e => choose(e.target.files)}/>
      {file ? <div className="selected-file"><img alt="" src={preview}/><div><strong>{file.name}</strong><small>{(file.size/1024/1024).toFixed(2)} MB</small></div><Button type="button" variant="ghost" size="icon" aria-label="Remove selected file" disabled={busy} onClick={() => {setFile(null);if(input.current) input.current.value=""}}><X/></Button></div> :
        <button type="button" className={'dropzone '+(drag?'drag':'')} onClick={()=>input.current?.click()} onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);choose(e.dataTransfer.files)}}>
          <span><UploadCloud/></span><strong>Drop an image or browse files</strong><small>JPG or PNG · Up to 10 MB</small>
        </button>}
      <label>Document name<Input disabled={busy} value={title} maxLength={160} required placeholder="e.g. Studio receipt" onChange={e=>setTitle(e.target.value)}/></label>
      {error && <p role="alert" className="error">{error}</p>}
      <div className="dialog-actions"><Button type="button" variant="outline" disabled={busy} onClick={close}>Cancel</Button><Button disabled={!file || !title.trim() || busy}>{busy?<LoaderCircle className="spin"/>:<FileImage/>}Add to library</Button></div>
    </form></DialogContent>
  </Dialog>
}
