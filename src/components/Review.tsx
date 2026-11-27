import { useState } from "react"
import { Check, Download, FileText, Image as ImageIcon, Pencil, RotateCcw, Trash2, X } from "lucide-react"
import { Button } from "./ui/button"
import { Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle } from "./ui/dialog"
import { Textarea } from "./ui/textarea"
import { library } from "@/lib/library"
import { errorText, maxAttempts, type Page } from "@/lib/types"
import { Highlight,ImageView,StatusBadge,pageDate,pageType } from "./Document"
export function Review({page,query,close,refresh,notify}: {page:Page;query:string;close:()=>void;refresh:()=>Promise<void>;notify:(message:string)=>void}) {
  const [edit,setEdit]=useState(false), [draft,setDraft]=useState(page.text), [remove,setRemove]=useState(false)
  const [error,setError]=useState(""), [busy,setBusy]=useState(false), [discard,setDiscard]=useState(false)
  const done = page.status==="ready" || page.status==="reviewed"
  function cancel(){ if(edit && draft!==page.text){setDiscard(true);return} close() }
  async function act(fn:()=>Promise<void>) {
    setBusy(true);setError("")
    try {await fn();await refresh()} catch(e){setError(errorText(e))} finally {setBusy(false)}
  }
  function download(){
    const a=document.createElement("a"), url=URL.createObjectURL(new Blob([page.text],{type:"text/plain;charset=utf-8"}))
    a.href=url;a.download=page.title.replace(/[/\\]/g,"-")+".txt";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  return <Dialog open onOpenChange={open=>{if(!open && !busy)cancel()}}>
    <DialogContent className="review-dialog" showCloseButton={false}>
      <div className="review-header"><DialogHeader><DialogTitle>{page.title}</DialogTitle><DialogDescription>{pageType(page)} · {pageDate(page)} · {page.filename}</DialogDescription></DialogHeader>
        <Button size="icon" variant="ghost" aria-label="Close document" disabled={busy} onClick={cancel}><X/></Button></div>
      <div className="review-panes">
        <section><h3><ImageIcon/>Original page</h3><div className="original"><ImageView page={page}/></div></section>
        <section className="text-pane"><h3><FileText/>Extracted text</h3><div className="review-status"><StatusBadge page={page}/></div>
          {done ? edit ? <Textarea aria-label="Edit extracted text" autoFocus value={draft} onChange={e=>setDraft(e.target.value)} className="text-editor"/> :
            <p className="transcript">{page.text ? <Highlight text={page.text} query={query}/> : "No text detected. You can enter it manually."}</p> :
            <p className="processing-message">{page.status==="failed" ? page.error || "Text extraction failed." : page.status==="queued" ? "This page is waiting for text extraction." : "Reading the words on this page…"}</p>}
        </section>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {remove || discard ? <div className="confirm-row"><span>{remove?"Delete the image and its saved text?":"Discard unsaved text changes?"}</span><Button variant="outline" disabled={busy} onClick={()=>{setDiscard(false);setRemove(false)}}>Keep {remove?"document":"editing"}</Button>
        <Button variant="destructive" disabled={busy} onClick={()=>remove?act(async()=>{await library.remove(page.id);close();notify("Document deleted.")}):close()}>{remove?"Delete document":"Discard changes"}</Button></div> :
      <div className="review-actions"><Button variant="ghost" size="icon" disabled={busy} aria-label="Delete document" onClick={()=>setRemove(true)}><Trash2/></Button><div>
        {done && (edit ? <><Button variant="outline" disabled={busy} onClick={()=>setEdit(false)}>Cancel edit</Button><Button disabled={busy} onClick={()=>act(async()=>{await library.update(page.id,{text:draft});setEdit(false);notify("Text saved and searchable.")})}><Check/>Save text</Button></> :
          <><Button variant="outline" onClick={download}><Download/>Export text</Button><Button onClick={()=>{setDraft(page.text);setEdit(true)}}><Pencil/>Edit text</Button></>)}
        {page.status==="failed" && page.attempts<maxAttempts && <Button disabled={busy} onClick={()=>act(()=>library.retry(page.id))}><RotateCcw/>Retry extraction</Button>}
      </div></div>}
    </DialogContent>
  </Dialog>
}
