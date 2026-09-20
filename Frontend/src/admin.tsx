import { useEffect, useState, type FormEvent } from 'react'

export type User = { id: number; username: string; is_admin: boolean; is_active: boolean; created_at: string }

async function request(url: string, csrf: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  headers.set('X-CSRF-Token', csrf)
  if (options.body) headers.set('Content-Type', 'application/json')
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `HTTP ${response.status}`)
  }
  return response.json()
}

export function AdminPanel({ csrf, currentUser }: { csrf: string; currentUser: string }) {
  const [users, setUsers] = useState<User[]>([])
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [resetFor, setResetFor] = useState<User|null>(null)

  const refresh = async () => {
    try { setUsers((await request('/api/admin/users', csrf)).users) }
    catch (error) { setError((error as Error).message) }
  }
  useEffect(() => { refresh() }, [csrf])
  const perform = async (url: string, options: RequestInit, message: string) => {
    setBusy(true); setError(''); setNotice('')
    try { await request(url, csrf, options); await refresh(); setNotice(message); setResetFor(null); return true }
    catch (error) { setError((error as Error).message); return false }
    finally { setBusy(false) }
  }
  const create = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    perform('/api/admin/users', { method: 'POST', body: JSON.stringify({
      username: data.get('username'), password: data.get('password'), is_admin: data.get('is_admin') === 'on',
    }) }, 'Felhasználó létrehozva.').then(ok => { if (ok) form.reset() })
  }
  const update = (user: User, field: 'is_active'|'is_admin') => {
    const next = !user[field]
    const action = field === 'is_active' ? (next ? 'aktiválod' : 'letiltod') : (next ? 'adminná teszed' : 'elveszed az admin jogát')
    if (!confirm(`Biztosan ${action} ezt a fiókot: ${user.username}?`)) return
    perform(`/api/admin/users/${user.id}`, { method: 'PATCH', body: JSON.stringify({ [field]: next }) }, 'Jogosultság frissítve.')
  }
  return <section className="management">
    <div className="page-heading"><h1>Felhasználók</h1><p>Fiókok, hozzáférés és jelszavak kezelése.</p></div>
    {error && <div className="error">{error}</div>}{notice && <div className="notice">{notice}</div>}
    <div className="management-grid"><form className="panel" onSubmit={create}><h2>Új felhasználó</h2>
      <label>Felhasználónév<input name="username" minLength={3} maxLength={32} pattern="[A-Za-z0-9._-]+" required autoComplete="off" /></label>
      <label>Jelszó<input name="password" type="password" minLength={12} required autoComplete="new-password" /></label>
      <label className="check"><input name="is_admin" type="checkbox"/> Admin jogosultság</label>
      <button disabled={busy}>Fiók létrehozása</button>
    </form><div className="panel"><h2>Meglévő fiókok</h2><div className="user-list">
      {users.map(user => <div className="user-row" key={user.id}><div><strong>{user.username}</strong><small>{user.is_admin ? 'Admin' : 'Felhasználó'} · {user.is_active ? 'Aktív' : 'Letiltva'}</small></div><div className="user-buttons">
        <button className="secondary" disabled={busy || user.username === currentUser} onClick={() => setResetFor(user)}>Jelszócsere</button>
        <button className="secondary" disabled={busy || user.username === currentUser} onClick={() => update(user, 'is_admin')}>{user.is_admin ? 'Admin jog elvétele' : 'Adminná tesz'}</button>
        <button className="secondary" disabled={busy || user.username === currentUser} onClick={() => update(user, 'is_active')}>{user.is_active ? 'Letiltás' : 'Aktiválás'}</button>
      </div></div>)}
    </div></div></div>
    {resetFor && <form className="panel reset-panel" onSubmit={event => { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); perform(`/api/admin/users/${resetFor.id}/password`, { method:'POST', body:JSON.stringify({ password:data.get('password') }) }, `${resetFor.username} jelszava frissítve; minden korábbi munkamenete megszűnt.`) }}>
      <h2>Új jelszó: {resetFor.username}</h2><label>Új jelszó<input name="password" type="password" minLength={12} required autoComplete="new-password"/></label><div className="form-actions"><button disabled={busy}>Jelszó mentése</button><button type="button" className="secondary" onClick={() => setResetFor(null)}>Mégse</button></div>
    </form>}
  </section>
}

export function AccountPanel({ csrf, onChanged }: { csrf: string; onChanged: () => void }) {
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    if (data.get('password') !== data.get('confirm')) { setError('Az új jelszavak nem egyeznek.'); return }
    setError(''); setBusy(true)
    try { await request('/api/auth/password', csrf, { method:'POST', body:JSON.stringify({ current_password:data.get('current'), password:data.get('password') }) }); onChanged() }
    catch (error) { setError((error as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="management"><div className="page-heading"><h1>Saját fiók</h1><p>Jelszó módosítása. Mentés után újra be kell jelentkezned.</p></div><form className="panel account-panel" onSubmit={submit}>
    <h2>Jelszócsere</h2>{error && <div className="error">{error}</div>}
    <label>Jelenlegi jelszó<input name="current" type="password" required autoComplete="current-password"/></label>
    <label>Új jelszó<input name="password" type="password" minLength={12} required autoComplete="new-password"/></label>
    <label>Új jelszó újra<input name="confirm" type="password" minLength={12} required autoComplete="new-password"/></label>
    <button disabled={busy}>Új jelszó mentése</button>
  </form></section>
}
