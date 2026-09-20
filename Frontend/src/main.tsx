import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { ChevronLeft, ChevronRight, Download, File as FileIcon, FileImage, FileText, Film, Folder, FolderPlus, LogOut, Maximize, Minimize, Pause, Pencil, Play, Trash2, Upload, X } from 'lucide-react'
import './styles.css'

type Entry = { name: string; path: string; type: 'directory'|'file'|'blocked'; size: number|null; modified: string; mime: string|null }
type Session = { username: string; csrf: string }

const encode = (path: string) => encodeURIComponent(path)
const api = async (url: string, options: RequestInit = {}, csrf?: string) => {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  if (csrf) headers.set('X-CSRF-Token', csrf)
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || `HTTP ${response.status}`) }
  return response.json()
}
const prettySize = (n: number|null) => n === null ? '—' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(1)} KB` : n < 1073741824 ? `${(n/1048576).toFixed(1)} MB` : `${(n/1073741824).toFixed(1)} GB`

function Login({ onLogin }: { onLogin: (s: Session) => void }) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const submit = async (e: React.FormEvent<HTMLFormElement>) => { e.preventDefault(); setBusy(true); setError(''); const form = new FormData(e.currentTarget)
    try { onLogin(await api('/api/auth/login', { method:'POST', body: JSON.stringify({username:form.get('username'), password:form.get('password')}) })) } catch(e) { setError((e as Error).message) } finally { setBusy(false) } }
  return <main className="login-wrap"><form className="login-card" onSubmit={submit}><div className="brand-mark"><Folder size={28}/></div><h1>Családi tárhely</h1><p>Jelentkezz be a megosztott fájlokhoz.</p><label>Felhasználónév<input name="username" autoComplete="username" required autoFocus /></label><label>Jelszó<input name="password" type="password" autoComplete="current-password" required /></label>{error && <div className="error">{error}</div>}<button disabled={busy}>{busy ? 'Belépés…' : 'Bejelentkezés'}</button></form></main>
}

function Modal({ item, images, close, select }: { item: Entry; images: Entry[]; close: () => void; select: (item: Entry) => void }) {
  const src = `/api/content?path=${encode(item.path)}`
  const isImage = item.mime?.startsWith('image/') === true
  const imageIndex = images.findIndex(image => image.path === item.path)
  const [playing, setPlaying] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)
  const touchStart = useRef<number|null>(null)
  const previewElement = useRef<HTMLDivElement>(null)
  const step = (amount: number) => {
    if (!isImage || images.length < 2 || imageIndex < 0) return
    select(images[(imageIndex + amount + images.length) % images.length])
  }
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
      if (event.key === 'ArrowLeft') step(-1)
      if (event.key === 'ArrowRight') step(1)
      if (event.key === ' ' && isImage) { event.preventDefault(); setPlaying(value => !value) }
    }
    window.addEventListener('keydown', keydown)
    return () => window.removeEventListener('keydown', keydown)
  }, [item.path, imageIndex, images.length, isImage])
  useEffect(() => {
    if (!playing || !isImage || images.length < 2) return
    const timer = window.setInterval(() => step(1), 4000)
    return () => window.clearInterval(timer)
  }, [playing, item.path, imageIndex, images.length, isImage])
  useEffect(() => {
    if (!isImage || images.length < 2 || imageIndex < 0) return
    const next = new Image()
    next.src = `/api/content?path=${encode(images[(imageIndex + 1) % images.length].path)}`
  }, [item.path, imageIndex, images.length, isImage])
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === previewElement.current)
    document.addEventListener('fullscreenchange', changed)
    return () => document.removeEventListener('fullscreenchange', changed)
  }, [])
  const toggleFullscreen = async () => {
    if (!document.fullscreenElement) await previewElement.current?.requestFullscreen()
    else await document.exitFullscreen()
  }
  return <div className="modal" onClick={close}><div ref={previewElement} className="preview" onClick={e=>e.stopPropagation()} onTouchStart={e=>touchStart.current=e.changedTouches[0].clientX} onTouchEnd={e=>{if(touchStart.current===null)return;const distance=e.changedTouches[0].clientX-touchStart.current;if(Math.abs(distance)>50)step(distance>0?-1:1);touchStart.current=null}}>
    <div className="preview-title"><h3>{item.name}</h3>{isImage&&<span>{imageIndex+1} / {images.length}</span>}</div><button className="close" title="Bezárás (Esc)" onClick={close}><X/></button>
    {isImage&&images.length>1&&<><button className="slide-arrow previous" title="Előző kép (←)" onClick={()=>step(-1)}><ChevronLeft/></button><button className="slide-arrow next" title="Következő kép (→)" onClick={()=>step(1)}><ChevronRight/></button></>}
    {isImage ? <img key={item.path} className="gallery-image" src={src} alt={item.name}/> : item.mime?.startsWith('video/') ? <video src={src} controls autoPlay/> : item.mime === 'application/pdf' ? <iframe src={src} title={item.name}/> : <p>Ehhez a fájltípushoz nincs előnézet.</p>}
    {isImage&&<div className="slideshow-controls"><button onClick={toggleFullscreen}>{fullscreen?<><Minimize/>Kilépés</>:<><Maximize/>Teljes képernyő</>}</button>{images.length>1&&<><button onClick={()=>setPlaying(value=>!value)}>{playing?<><Pause/>Szünet</>:<><Play/>Diavetítés</>}</button><span>{playing?'Következő kép 4 másodperc múlva':'← és → gombokkal is lapozhatsz'}</span></>}</div>}
  </div></div>
}

function App() {
  const [session,setSession]=useState<Session|null>(null), [loading,setLoading]=useState(true), [path,setPath]=useState(''), [items,setItems]=useState<Entry[]>([]), [error,setError]=useState(''), [progress,setProgress]=useState<number|null>(null), [preview,setPreview]=useState<Entry|null>(null), [drag,setDrag]=useState(false)
  const picker=useRef<HTMLInputElement>(null)
  useEffect(()=>{ api('/api/auth/me').then(setSession).catch(()=>{}).finally(()=>setLoading(false)) },[])
  const refresh=async(p=path)=>{try{setError('');const d=await api(`/api/files?path=${encode(p)}`);setItems(d.items);setPath(d.path)}catch(e){setError((e as Error).message)}}
  useEffect(()=>{if(session)refresh('')},[session])
  const mutate=async(url:string, options:RequestInit)=>{try{await api(url,options,session!.csrf);await refresh()}catch(e){setError((e as Error).message)}}
  const upload=(files:FileList|File[])=>{if(!files.length)return;const data=new FormData();data.append('path',path);Array.from(files).forEach(f=>data.append('files',f));const xhr=new XMLHttpRequest();xhr.open('POST','/api/upload');xhr.setRequestHeader('X-CSRF-Token',session!.csrf);xhr.upload.onprogress=e=>e.lengthComputable&&setProgress(Math.round(e.loaded/e.total*100));xhr.onload=()=>{setProgress(null);if(xhr.status>=200&&xhr.status<300)refresh();else{try{setError(JSON.parse(xhr.responseText).detail)}catch{setError('Sikertelen feltöltés')}}};xhr.onerror=()=>{setProgress(null);setError('Hálózati hiba')};setProgress(0);xhr.send(data)}
  const crumbs=[{name:'Kezdőlap',path:''},...path.split('/').filter(Boolean).map((name,i,a)=>({name,path:a.slice(0,i+1).join('/')}))]
  const images=items.filter(it=>it.type==='file'&&it.mime?.startsWith('image/'))
  const icon=(it:Entry)=>it.type==='directory'?<Folder/>:it.mime?.startsWith('image/')?<FileImage/>:it.mime?.startsWith('video/')?<Film/>:it.mime==='application/pdf'?<FileText/>:<FileIcon/>
  const open=(it:Entry)=>{if(it.type==='directory')refresh(it.path);else if(it.type==='file'&&(it.mime?.startsWith('image/')||it.mime?.startsWith('video/')||it.mime==='application/pdf'))setPreview(it)}
  if(loading)return <div className="center">Betöltés…</div>; if(!session)return <Login onLogin={setSession}/>
  return <div className="app" onDragOver={e=>{e.preventDefault();setDrag(true)}} onDragLeave={()=>setDrag(false)} onDrop={e=>{e.preventDefault();setDrag(false);upload(e.dataTransfer.files)}}>
    {drag&&<div className="drop"><Upload size={48}/><b>Engedd el a fájlokat</b></div>}
    <header><div className="brand"><div className="brand-mark"><Folder/></div><span>Családi tárhely</span></div><div className="user"><span>{session.username}</span><button className="icon-btn" title="Kijelentkezés" onClick={async()=>{await api('/api/auth/logout',{method:'POST'},session.csrf);setSession(null)}}><LogOut/></button></div></header>
    <main className="content"><div className="toolbar"><nav>{crumbs.map((c,i)=><React.Fragment key={c.path}><button onClick={()=>refresh(c.path)}>{c.name}</button>{i<crumbs.length-1&&<span>/</span>}</React.Fragment>)}</nav><div className="actions"><button className="secondary" onClick={()=>{const n=prompt('Új mappa neve:');if(n)mutate(`/api/folders?name=${encode(n)}`,{method:'POST',body:JSON.stringify({path})})}}><FolderPlus/>Új mappa</button><button onClick={()=>picker.current?.click()}><Upload/>Feltöltés</button><input ref={picker} hidden type="file" multiple onChange={e=>e.target.files&&upload(e.target.files)}/></div></div>
    {error&&<div className="error banner">{error}<button onClick={()=>setError('')}><X/></button></div>}{progress!==null&&<div className="progress-wrap"><div><span>Feltöltés</span><b>{progress}%</b></div><progress value={progress} max="100"/></div>}
    <section className="file-list"><div className="row head"><span>Név</span><span>Méret</span><span>Módosítva</span><span></span></div>{items.length===0&&<div className="empty"><Folder size={50}/><h2>Ez a mappa üres</h2><p>Húzz ide fájlokat, vagy használd a Feltöltés gombot.</p></div>}{items.map(it=><div className={`row ${it.type==='blocked'?'blocked':''}`} key={it.path}><button className="filename" onClick={()=>open(it)} disabled={it.type==='blocked'}>{icon(it)}<span>{it.name}</span></button><span>{prettySize(it.size)}</span><time>{new Date(it.modified).toLocaleString('hu-HU')}</time><div className="row-actions">{it.type==='file'&&<a className="icon-btn" title="Letöltés" href={`/api/content?path=${encode(it.path)}&download=true`}><Download/></a>}<button className="icon-btn" title="Átnevezés" disabled={it.type==='blocked'} onClick={()=>{const n=prompt('Új név:',it.name);if(n&&n!==it.name)mutate('/api/rename',{method:'POST',body:JSON.stringify({path:it.path,new_name:n})})}}><Pencil/></button><button className="icon-btn danger" title="Törlés" disabled={it.type==='blocked'} onClick={()=>confirm(`Biztosan törlöd: ${it.name}?${it.type==='directory'?'\nCsak üres mappa törölhető.':''}`)&&mutate(`/api/files?path=${encode(it.path)}`,{method:'DELETE'})}><Trash2/></button></div></div>)}</section></main>{preview&&<Modal item={preview} images={images} select={setPreview} close={()=>setPreview(null)}/>}</div>
}
createRoot(document.getElementById('root')!).render(<App />)
