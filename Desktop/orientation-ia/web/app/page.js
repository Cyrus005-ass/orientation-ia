
"use client";

import { useEffect, useState } from 'react';

const API_BASE_RAW = process.env.NEXT_PUBLIC_API_URL || '';
const API_BASE_FALLBACK = process.env.NODE_ENV === 'production' ? 'orientation-api.onrender.com' : '';
const API_BASE = (API_BASE_RAW || API_BASE_FALLBACK)
  ? ((API_BASE_RAW || API_BASE_FALLBACK).startsWith('http')
      ? (API_BASE_RAW || API_BASE_FALLBACK)
      : `https://${API_BASE_RAW || API_BASE_FALLBACK}`)
  : '';

const money = (value) => {
  if (value === undefined || value === null || value === '') return '--';
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(2) : String(value);
};

const pct = (value) => {
  if (value === undefined || value === null || value === '') return '--';
  const n = Number(value);
  return Number.isFinite(n) ? `${n.toFixed(2)}%` : String(value);
};

async function api(path, token, init = {}) {
  const url = `${API_BASE}${path}`;
  const headers = { ...(init.headers || {}) };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
    headers['X-Agent-Token'] = token;
  }
  if (init.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  const res = await fetch(url, { ...init, headers, cache: 'no-store' });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function tone(direction) {
  return String(direction || '').toUpperCase() === 'LONG' ? 'good' : 'bad';
}

export default function Home() {
  const [tab, setTab] = useState('signals');
  const [token, setToken] = useState('');
  const [signals, setSignals] = useState([]);
  const [state, setState] = useState(null);
  const [health, setHealth] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('Synchronisation en attente.');
  const [accountName, setAccountName] = useState('');
  const [deviceName, setDeviceName] = useState('');
  const [requestId, setRequestId] = useState('');
  const [accessStatus, setAccessStatus] = useState('');
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    setToken(localStorage.getItem('orientation_token') || '');
    setAccountName(localStorage.getItem('orientation_account') || '');
    setDeviceName(localStorage.getItem('orientation_device') || 'Telephone mobile');
    setRequestId(localStorage.getItem('orientation_request') || '');
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    }
  }, []);

  useEffect(() => {
    localStorage.setItem('orientation_token', token);
  }, [token]);

  useEffect(() => {
    localStorage.setItem('orientation_account', accountName);
  }, [accountName]);

  useEffect(() => {
    localStorage.setItem('orientation_device', deviceName);
  }, [deviceName]);

  useEffect(() => {
    localStorage.setItem('orientation_request', requestId);
  }, [requestId]);

  useEffect(() => {
    if (!requestId) return undefined;
    setPolling(true);
    const timer = setInterval(() => {
      pollAccessStatus().catch(() => {});
    }, 5000);
    pollAccessStatus().catch(() => {});
    return () => clearInterval(timer);
  }, [requestId]);

  async function refresh() {
    if (!token) {
      setStatus('Ajoute un token pour synchroniser.');
      return;
    }

    setLoading(true);
    try {
      const [healthData, live, liveState, metricsData, logsData] = await Promise.all([
        api('/health', token),
        api('/live/signals?symbols=EURUSDm,XAUUSDm,BTCUSDm&timeframes=M5,M15', token),
        api('/live/state', token),
        api('/live/training/metrics', token).catch(() => ({})),
        api('/live/training/log?lines=20', token).catch(() => ({ lines: [] })),
      ]);
      setHealth(healthData);
      setSignals((live.signals || []).filter((item) => item.status === 'TRADE'));
      setState(liveState);
      setMetrics(metricsData);
      setLogs(logsData.lines || []);
      setStatus('Synchronisation reussie.');
    } catch (err) {
      setStatus(`Etat: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function requestAccess() {
    if (!accountName.trim()) {
      setAccessStatus('Renseigne un nom utilisateur.');
      return;
    }

    try {
      const payload = {
        account_name: accountName.trim(),
        device_name: deviceName.trim() || 'Telephone mobile',
        device_id: `${navigator.userAgent}-${screen.width}x${screen.height}`,
      };
      const data = await api('/access/request', '', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (data.request_id) setRequestId(data.request_id);
      if (data.token) setToken(data.token);
      setAccessStatus(data.status === 'APPROVED' ? 'Acces valide.' : 'Demande envoyee.');
      if (data.status === 'APPROVED') refresh();
    } catch (err) {
      setAccessStatus(`Erreur acces: ${err.message}`);
    }
  }

  async function pollAccessStatus() {
    if (!requestId) return;
    try {
      const data = await api(`/access/request/status?request_id=${encodeURIComponent(requestId)}`, token);
      if (data.status === 'APPROVED' && data.token) {
        setToken(data.token);
        setAccessStatus('Session approuvee par le desktop.');
        setPolling(false);
        await refresh();
      } else if (data.status === 'REJECTED') {
        setAccessStatus(`Demande refusee: ${data.note || 'sans motif'}`);
        setPolling(false);
      } else {
        setAccessStatus(`Demande ${data.status || 'PENDING'} en attente.`);
      }
    } catch (err) {
      setAccessStatus(`Suivi acces: ${err.message}`);
    }
  }

  const activeCount = signals.length;
  const hitRate = state?.journal_summary?.hit_rate_pct;
  const pendingRequests = health?.access?.pending_requests;
  const activeSessions = health?.access?.active_sessions;
  const chipStatus = health?.status || '--';
  const chipProvider = health?.llm?.provider || '--';
  const statusTone = status.startsWith('Synchronisation') ? 'ok' : status.startsWith('Etat:') || status.startsWith('Erreur') ? 'bad' : 'warn';

  return (
    <main className="shell">
      <header className="hero panel">
        <div className="hero-copy">
          <div className="eyebrow">Orientation IA Live</div>
          <h1>Un cockpit clair pour mobile, web et desktop.</h1>
          <p>
            Les signaux, le risque et les validations restent dans un seul endroit.
            L'interface est plus lisible, plus compacte et plus rapide a parcourir.
          </p>
          <div className="hero-stats">
            <div className="statCard">
              <span>Signaux</span>
              <strong>{activeCount}</strong>
            </div>
            <div className="statCard">
              <span>Hit rate</span>
              <strong>{pct(hitRate)}</strong>
            </div>
            <div className="statCard">
              <span>Acces</span>
              <strong>{pendingRequests ?? '--'} / {activeSessions ?? '--'}</strong>
            </div>
          </div>
        </div>
        <div className="hero-panel">
          <div className="tokenStack">
            <input value={token} onChange={(e) => setToken(e.target.value.trim())} placeholder="Token session ou code PRO" />
            <button onClick={refresh} disabled={!token || loading}>{loading ? '...' : 'Synchroniser'}</button>
          </div>
          <div className="hero-chips">
            <span className={`chip statusChip ${statusTone}`}>Etat: {status}</span>
            <span className="chip">API: {chipStatus}</span>
            <span className="chip">LLM: {chipProvider}</span>
          </div>
        </div>
      </header>

      <section className="panel section-card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <h2>Demonstration rapide</h2>
          <span className="muted">Parcours utilisateur de A a Z</span>
        </div>
        <div className="miniGrid">
          <div className="miniCard"><span>1</span><strong>Connexion</strong></div>
          <div className="miniCard"><span>2</span><strong>Synchroniser</strong></div>
          <div className="miniCard"><span>3</span><strong>Lire les signaux</strong></div>
          <div className="miniCard"><span>4</span><strong>Demander l'acces</strong></div>
          <div className="miniCard"><span>5</span><strong>Valider sur desktop</strong></div>
          <div className="miniCard"><span>6</span><strong>Executer</strong></div>
        </div>
      </section>

      <nav className="tabs panel">
        <button className={tab === 'signals' ? 'active' : ''} onClick={() => setTab('signals')}>Signaux</button>
        <button className={tab === 'account' ? 'active' : ''} onClick={() => setTab('account')}>Acces mobile</button>
        <a href="/dashboard">Dashboard</a>
        <a href="/changelog">Changelog</a>
      </nav>

      {tab === 'signals' ? (
        <section className="grid-layout">
          <article className="panel section-card">
            <div className="section-head">
              <h2>Signaux du jour</h2>
              <span className="muted">MAJ locale: {new Date().toLocaleTimeString()}</span>
            </div>
            <div className="signal-grid">
              {signals.length ? signals.map((s) => (
                <article className={`signalCard ${tone(s.direction)}`} key={`${s.symbol}-${s.timeframe}-${s.direction}`}>
                  <div className="signal-head">
                    <strong>{s.symbol} {s.timeframe}</strong>
                    <span className={`direction ${tone(s.direction)}`}>{s.direction}</span>
                  </div>
                  <div className="signal-line">Entry <b>{money(s.entry)}</b> | SL <b>{money(s.stop_loss)}</b></div>
                  <div className="signal-line">TP1 <b>{money(s.tp1)}</b> | TP2 <b>{money(s.tp2)}</b></div>
                  <div className="signal-line">RR <b>{money(s.rr)}</b> | Score <b>{s.confluence_score || '--'}</b></div>
                  <p className="signal-note">{s.trigger || s.note || 'Confluence technique disponible.'}</p>
                </article>
              )) : <div className="emptyState">Aucun signal pour le moment.</div>}
            </div>
          </article>

          <aside className="stack">
            <article className="panel section-card">
              <div className="section-head">
                <h2>Lecture rapide</h2>
              </div>
              <div className="miniGrid">
                <div className="miniCard"><span>Pending</span><strong>{pendingRequests ?? '--'}</strong></div>
                <div className="miniCard"><span>Active</span><strong>{activeSessions ?? '--'}</strong></div>
                <div className="miniCard"><span>Wins</span><strong>{state?.journal_summary?.win ?? '--'}</strong></div>
                <div className="miniCard"><span>Loss</span><strong>{state?.journal_summary?.loss ?? '--'}</strong></div>
              </div>
            </article>

            <article className="panel section-card">
              <div className="section-head">
                <h2>Brief marche</h2>
              </div>
              <div className="monoBlock">{state?.brief || 'Aucun brief disponible.'}</div>
            </article>
          </aside>
        </section>
      ) : (
        <section className="grid-layout">
          <article className="panel section-card">
            <div className="section-head">
              <h2>Acces mobile</h2>
              <span className="muted">Flux de validation desktop</span>
            </div>
            <div className="stackInputs">
              <input value={accountName} onChange={(e) => setAccountName(e.target.value)} placeholder="Nom utilisateur" />
              <input value={deviceName} onChange={(e) => setDeviceName(e.target.value)} placeholder="Nom appareil" />
              <button onClick={requestAccess}>Demander l'acces</button>
            </div>
            <div className="accessNote">{accessStatus || 'Demande une validation sur le dashboard desktop. Tu verras ensuite le token actif ici.'}</div>
            <div className="chipRow">
              <span className="chip">Request: {requestId || '--'}</span>
              <span className="chip">Polling: {polling ? 'ON' : 'OFF'}</span>
            </div>
          </article>

          <article className="panel section-card">
            <div className="section-head">
              <h2>Etat du compte</h2>
            </div>
            <div className="miniGrid">
              <div className="miniCard"><span>Mode</span><strong>{state?.profit_mode?.mode || health?.mode || '--'}</strong></div>
              <div className="miniCard"><span>Quota</span><strong>{health?.signals_quota_left ?? '--'}</strong></div>
              <div className="miniCard"><span>Signal cache</span><strong>{state?.signals?.signals?.length || 0}</strong></div>
              <div className="miniCard"><span>Runtime</span><strong>{health?.scheduler_running ? 'ON' : 'OFF'}</strong></div>
            </div>
            <div className="monoBlock" style={{ marginTop: 12 }}>{JSON.stringify(metrics || {}, null, 2)}</div>
          </article>
        </section>
      )}

      <section className="panel section-card fullWidth">
        <div className="section-head">
          <h2>Journal runtime</h2>
          <span className="muted">Dernieres lignes: {logs.length}</span>
        </div>
        <div className="monoBlock">{logs.join('\n') || 'Aucun log pour le moment.'}</div>
      </section>
    </main>
  );
}

