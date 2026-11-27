import { useCallback, useEffect, useRef, useState } from "react"
import { AlignJustify, ArrowDownWideNarrow, Check, ChevronDown, CircleHelp, FileImage, Files, FolderOpen, Grid2X2, Laptop, ListFilter, LoaderCircle, LogOut, Plus, Search, Star, UserRound, X } from "lucide-react"
import { Button } from "./components/ui/button"
import { Input } from "./components/ui/input"
import { DropdownMenu,DropdownMenuContent,DropdownMenuItem,DropdownMenuSeparator,DropdownMenuTrigger } from "./components/ui/dropdown-menu"
import { Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription } from "./components/ui/dialog"
import { ChoiceMark,DocumentCard } from "./components/Document"
import { Upload } from "./components/Upload"
import { Review } from "./components/Review"
import { AccountAccess } from "./components/Account"
import { library } from "./lib/library"
import { processQueue } from "./lib/local"
import { ocrEndpoint } from "./lib/recognize"
import { apiBase,auth,Unauthorized } from "./lib/api"
import { errorText,statuses,type Page } from "./lib/types"
function Choice({label,icon,items,value,onSelect}: {label:string;icon:React.ReactNode;items:Record<string,string>;value:string;onSelect:(v:string)=>void}) {
  return <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" className="choice" aria-label={label+" filter or order"}>{icon}{items[value]}<ChevronDown className="chevron"/></Button></DropdownMenuTrigger>
    <DropdownMenuContent align="start" className="min-w-40">{Object.entries(items).map(([v,name])=><DropdownMenuItem key={v} onSelect={()=>onSelect(v)}><ChoiceMark active={v===value}/>{name}</DropdownMenuItem>)}</DropdownMenuContent></DropdownMenu>
}
function Header({email,logout,help}:{email:string;logout:()=>void;help:()=>void}) {
  return <header className="topbar"><div className="top-inner"><div className="breadcrumb"><img src="/icon.svg" alt=""/><strong>Workspace</strong><span className="crumb-line"/><span>Library</span></div>
    <nav aria-label="Account navigation" className="header-right account-links">
      <Button variant="ghost" size="icon" aria-label="About this library" onClick={help}><CircleHelp/></Button>
      {email ? <Button variant="ghost" onClick={logout}>Sign out</Button> : <a href="/login">Log in</a>}
      <Button asChild variant="outline" size="icon" className="account"><a href="/profile" aria-label="Your profile"><UserRound/></a></Button>
    </nav></div></header>
}
function Workspace({email,expired}:{email:string;expired:()=>void}) {
  const [pages,setPages]=useState<Page[]>([]), [found,setFound]=useState<Page[]>([])
  const [loading,setLoading]=useState(true), [error,setError]=useState(""), [notice,setNotice]=useState("")
  const [query,setQuery]=useState(""), [searchTerm,setSearchTerm]=useState("")
  const [tab,setTab]=useState("all"), [status,setStatus]=useState("all"), [mime,setMime]=useState("all"), [sort,setSort]=useState("new")
  const [view,setView]=useState("grid"),[upload,setUpload]=useState(false),[selected,setSelected]=useState<string | null>(null),[help,setHelp]=useState(false)
  const seq=useRef(0), search=useRef<HTMLInputElement>(null)
  const refresh=useCallback(async()=>{
    const token=++seq.current
    try {
      const [all,matched]=await Promise.all([library.list(),searchTerm?library.list(searchTerm):Promise.resolve(null)])
      if(token!==seq.current)return
      setPages(all);setFound(matched??all);setError("")
    }catch(e){if(token===seq.current){if(e instanceof Unauthorized)expired();else setError(errorText(e))}}
    finally {if(token===seq.current)setLoading(false)}
  },[searchTerm,expired])
  useEffect(()=>{const id=setTimeout(()=>setSearchTerm(query.trim()),120);return()=>clearTimeout(id)},[query])
  useEffect(()=>{void refresh();window.addEventListener("focus",refresh);return()=>{seq.current++;window.removeEventListener("focus",refresh)}},[refresh])
  const jobs=pages.some(p=>p.status==="queued"||p.status==="processing")
  useEffect(()=>{
    if(!jobs)return
    let live=true
    function tick(){if(!apiBase)void processQueue(()=>{if(live)void refresh()}).catch(e=>{if(live)setError(errorText(e))});void refresh()}
    tick();const id=setInterval(tick,1700)
    return()=>{live=false;clearInterval(id)}
  },[jobs,refresh])
  useEffect(()=>{if(!notice)return;const id=setTimeout(()=>setNotice(""),3200);return()=>clearTimeout(id)},[notice])
  useEffect(()=>{
    const focus=(e:KeyboardEvent)=>{if(e.key==="/"&&!upload&&!selected&&!help&&!(e.target instanceof HTMLInputElement)&&!(e.target instanceof HTMLTextAreaElement)){e.preventDefault();search.current?.focus()}}
    window.addEventListener("keydown",focus);return()=>window.removeEventListener("keydown",focus)
  },[upload,selected,help])
  const active=pages.find(p=>p.id===selected)
  const visible=found.filter(p=>(tab==="all"||p.starred)&&(status==="all"||p.status===status)&&(mime==="all"||p.mime===mime))
    .sort((a,b)=>sort==="name"?a.title.localeCompare(b.title):sort==="old"?a.createdAt.localeCompare(b.createdAt):b.createdAt.localeCompare(a.createdAt))
  const clear=()=>{setQuery("");setStatus("all");setMime("all");setTab("all")}
  async function star(page:Page) {
    try{await library.update(page.id,{starred:!page.starred});await refresh()}catch(e){if(e instanceof Unauthorized)expired();else setError(errorText(e))}
  }
  async function logout() {try{await auth.signOut();expired()}catch(e){setError(errorText(e))}}
  const recent=pages.filter(page=>apiBase || !page.imageUrl).sort((a,b)=>b.createdAt.localeCompare(a.createdAt)).slice(0,5)
  return <><Header email={email} help={()=>setHelp(true)} logout={logout}/>
    {location.pathname==="/profile" ? <main className="workspace profile-page"><a href="/">Back to library</a><h1>Your profile</h1><p>{email || "Local workspace"}</p><section className="recent-files"><h3>Recently uploaded</h3>{recent.length?recent.map(page=><button key={page.id} className="recent-file" onClick={()=>{setSelected(page.id)}}><span><FileImage/>{page.title}</span><small>{new Date(page.createdAt).toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"})}</small></button>):<p>No uploaded files yet.</p>}</section></main> : <main className="workspace">
      <section className="hero" aria-labelledby="library-title"><div className="hero-pattern"/><img className="hero-art" src="/scan.webp" alt=""/>
        <div className="hero-content"><h1 id="library-title">Document library</h1><p>Find a scanned page by the words inside it.</p>
        <div className="search-box"><Search/><Input ref={search} aria-label="Search documents" placeholder="Search names or text inside documents…" value={query} onChange={e=>setQuery(e.target.value)}/>
          {query?<button aria-label="Clear search" onClick={()=>{setQuery("");search.current?.focus()}}><X/></button>:<kbd>/</kbd>}
        </div></div></section>
      <section className="collection" aria-label="Documents">
        <div className="collection-head"><div className="tabs">
          <button className={tab==="all"?"selected":""} aria-pressed={tab==="all"} onClick={()=>setTab("all")}><Files/>All documents <span>{pages.length}</span></button>
          <button className={tab==="starred"?"selected":""} aria-pressed={tab==="starred"} onClick={()=>setTab("starred")}><Star/>Starred <span>{pages.filter(p=>p.starred).length}</span></button>
        </div><Button onClick={()=>setUpload(true)} className="upload-btn"><Plus/>Upload page</Button></div>
        <div className="filterbar"><div className="filters">
          <Choice label="Status" icon={<ListFilter/>} items={{all:"All statuses",...statuses}} value={status} onSelect={setStatus}/>
          <Choice label="File type" icon={<FileImage/>} items={{all:"File type","image/jpeg":"JPG","image/png":"PNG"}} value={mime} onSelect={setMime}/>
        </div><div className="display-controls"><Choice label="Sort" icon={<ArrowDownWideNarrow/>} items={{new:"Newest first",old:"Oldest first",name:"Name A–Z"}} value={sort} onSelect={setSort}/>
          <div className="view-switch"><button aria-label="Grid view" aria-pressed={view==="grid"} onClick={()=>setView("grid")}><Grid2X2/></button><button aria-label="List view" aria-pressed={view==="list"} onClick={()=>setView("list")}><AlignJustify/></button></div>
        </div></div>
        {error && <div className="error-bar" role="alert">{error}<Button variant="outline" size="sm" onClick={()=>void refresh()}>Try again</Button></div>}
        {searchTerm && <p className="result-count" aria-live="polite">{visible.length} {visible.length===1?"match":"matches"} for “{searchTerm}”</p>}
        {loading ? <div className="empty"><LoaderCircle className="spin"/>Opening library…</div> : visible.length?<div className={'documents '+view}>{visible.map(page=><DocumentCard key={page.id} page={page} query={searchTerm} open={()=>setSelected(page.id)} star={()=>void star(page)}/>)}</div>:
          !error && <div className="empty"><FolderOpen/><h2>{searchTerm||mime!=="all"||status!=="all"?"No matching pages":tab==="starred"?"No starred pages":"Your library is empty"}</h2><p>{searchTerm||mime!=="all"||status!=="all"?"Try another phrase or clear your filters.":tab==="starred"?"Use the star on a document to keep it here.":"Upload a printed page to start your collection."}</p>
          <Button variant="outline" onClick={()=>pages.length?clear():setUpload(true)}>{pages.length?"Show all documents":"Upload a page"}</Button></div>}
      </section>
    </main>}
    {upload&&<Upload close={()=>setUpload(false)} added={async page=>{setUpload(false);clear();setSort("new");await refresh();setSelected(page.id);setNotice("Page added to the queue.")}}/>}
    {active&&<Review key={active.id} page={active} query={searchTerm} close={()=>setSelected(null)} refresh={refresh} notify={setNotice}/>}

    {help&&<Dialog open onOpenChange={v=>{if(!v)setHelp(false)}}><DialogContent><DialogHeader><DialogTitle>About this library</DialogTitle><DialogDescription>{apiBase?"Your saved pages belong to your signed-in account.":ocrEndpoint ? "Images are sent to the configured OCR service. Your images and saved text are stored in this browser." : "The six example pages are yours to explore. New uploads are processed and saved in this browser on this device. Clearing site data removes your local library."}</DialogDescription></DialogHeader><Button onClick={()=>setHelp(false)}>Done</Button></DialogContent></Dialog>}
    {notice&&<div className="toast" role="status"><Check/>{notice}</div>}
  </>
}
export default function App() {
  const [session,setSession]=useState<string | null | undefined>(apiBase?undefined:""),[error,setError]=useState("")
  const expired=useCallback(()=>setSession(null),[])
  const check=useCallback(async()=>{setError("");try{setSession((await auth.session()).email)}catch(e){if(e instanceof Unauthorized)expired();else setError(errorText(e))}},[expired])
  useEffect(()=>{if(apiBase)void check()},[check])
  if(session===undefined)return <main className="empty">{error?<>{error}<Button onClick={check}>Try again</Button></>:<LoaderCircle className="spin"/>}</main>
  if(location.pathname==="/login" || location.pathname==="/register" || session===null)return <AccountAccess initialMode={location.pathname==="/register"?"register":"login"} signedIn={()=>location.assign("/profile")}/>
  return <Workspace email={session} expired={expired}/>
}
