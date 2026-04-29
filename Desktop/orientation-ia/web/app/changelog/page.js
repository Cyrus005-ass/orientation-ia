const items = [
  'Interface harmonisee pour mobile, dashboard et desktop.',
  'Validation desktop conservee pour les actions sensibles.',
  'Cartes et tableaux mieux adaptes aux petits ecrans.',
  'Les routes publiques restent legere et rapides a charger.'
];

export default function ChangelogPage() {
  return (
    <main className="shell">
      <header className="hero panel">
        <div className="hero-copy">
          <div className="eyebrow">Changelog</div>
          <h1>Historique clair des evolutions.</h1>
          <p>Un resume concis des blocs qui comptent pour les surfaces web, mobile et desktop.</p>
        </div>
        <div className="hero-panel">
          <a className="linkBtn" href="/">Retour a l'accueil</a>
        </div>
      </header>

      <section className="panel section-card" style={{ marginBottom: 16 }}>
        <div className="section-head">
          <h2>Comment utiliser</h2>
          <span className="muted">Version courte pour debuter</span>
        </div>
        <div className="miniGrid">
          <div className="miniCard"><span>1</span><strong>Mobile</strong></div>
          <div className="miniCard"><span>2</span><strong>Dashboard</strong></div>
          <div className="miniCard"><span>3</span><strong>Desktop</strong></div>
          <div className="miniCard"><span>4</span><strong>Admin</strong></div>
        </div>
      </section>

      <section className="panel section-card">
        <div className="section-head">
          <h2>Points clefs</h2>
          <span className="muted">Version actuelle</span>
        </div>
        <div className="signal-grid">
          {items.map((item) => (
            <div className="signalCard" key={item}>
              <div className="signal-line">{item}</div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

