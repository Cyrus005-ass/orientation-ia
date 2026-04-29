export default function DashboardPage() {
  return (
    <main className="shell">
      <header className="hero panel">
        <div className="hero-copy">
          <div className="eyebrow">Web cockpit</div>
          <h1>Dashboard compact pour ecran bureau et tablette.</h1>
          <p>Cette vue garde le parcours rapide: lecture des signaux, supervision du risque et bascule vers la validation desktop sans surcharge visuelle.</p>
          <div className="hero-chips" style={{ marginTop: 16 }}>
            <span className="chip">Lecture rapide</span>
            <span className="chip">Mobile ready</span>
            <span className="chip">Desktop handoff</span>
          </div>
        </div>
        <div className="hero-panel">
          <div className="tokenStack">
            <a className="linkBtn" href="/">Vue mobile</a>
            <a className="linkBtn" href="/desktop">Desktop</a>
            <a className="linkBtn" href="/admin">Admin</a>
          </div>
        </div>
      </header>

      <section className="panel section-card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <h2>Demonstration rapide</h2>
          <span className="muted">Comprendre le dashboard en 4 etapes</span>
        </div>
        <div className="miniGrid">
          <div className="miniCard"><span>1</span><strong>Ouvrir</strong></div>
          <div className="miniCard"><span>2</span><strong>Lire</strong></div>
          <div className="miniCard"><span>3</span><strong>Basculer</strong></div>
          <div className="miniCard"><span>4</span><strong>Valider</strong></div>
        </div>
      </section>

      <section className="grid-layout">
        <article className="panel section-card">
          <div className="section-head">
            <h2>Flux principal</h2>
            <span className="muted">Lecture seule</span>
          </div>
          <div className="signal-grid">
            <div className="signalCard good">
              <div className="signal-head"><strong>Signal live</strong><span className="direction good">TRADE</span></div>
              <div className="signal-line">Les cartes signal affichent entree, SL, TP et RR de facon lisible.</div>
            </div>
            <div className="signalCard bad">
              <div className="signal-head"><strong>Risque</strong><span className="direction bad">GATE</span></div>
              <div className="signal-line">Le risk gate bloque avant l'execution si les conditions ne sont pas reunies.</div>
            </div>
            <div className="signalCard good">
              <div className="signal-head"><strong>Validation</strong><span className="direction good">EXECUTE</span></div>
              <div className="signal-line">Le desktop reste le point d'approval final pour les actions sensibles.</div>
            </div>
          </div>
        </article>

        <aside className="stack">
          <article className="panel section-card">
            <div className="section-head"><h2>Parcours</h2></div>
            <div className="miniGrid">
              <div className="miniCard"><span>1</span><strong>Mobile</strong></div>
              <div className="miniCard"><span>2</span><strong>Web</strong></div>
              <div className="miniCard"><span>3</span><strong>Desktop</strong></div>
              <div className="miniCard"><span>4</span><strong>Validation</strong></div>
            </div>
          </article>

          <article className="panel section-card">
            <div className="section-head"><h2>Notes</h2></div>
            <div className="monoBlock">Le dashboard sert de tableau de bord compact pour superviser les signaux et basculer vers le desktop quand une action manuelle est requise.</div>
          </article>
        </aside>
      </section>
    </main>
  );
}

