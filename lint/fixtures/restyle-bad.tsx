// The first three elements borrow a kit control class and restyle it inline (UI009). A card
// sizes to its content, so the padding tweak on the last one is not flagged.
export function Cards({ active, dim, onPick }: { active: boolean; dim: string; onPick: () => void }) {
  return (
    <div>
      <button type="button" className="btn" onClick={() => onPick()}
        style={{ display: 'flex', alignItems: 'flex-start', padding: '10px 12px', background: active ? dim : 'var(--surface-1)' }}>
        <span style={{ display: 'block' }}>Incident</span>
        <span style={{ display: 'block' }}>Something is broken</span>
      </button>
      <span className={`badge ${active ? 'on' : ''}`} style={{ height: 30, whiteSpace: 'normal' }}>Long text</span>
      <div className={"tab wide"} style={{ padding: 0, borderRadius: 4 }} />
      <div className="card" style={{ padding: 0 }} />
    </div>
  );
}
