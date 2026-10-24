// Nothing here may be flagged.
import { useConfirm } from './kit';
export function Good() {
  const confirmDelete = useConfirm();
  const dialog = { prompt: () => null };
  dialog.prompt();
  const href = '#/action?item=ac_1';
  const anchor = '#main';
  const style = { color: 'var(--text-primary)', zIndex: 0, transition: 'opacity var(--dur-fast)' };
  window.confirm('kept for a migration'); // core-exception: EXC-003
  const kitSpacing = <button className="btn" data-variant="ghost" style={{ marginLeft: 8 }}>Save</button>;
  const appClass = <button className="pick-card" style={{ padding: '10px 12px', display: 'flex' }}>Pick</button>;
  const border = 'var(--border-default)';
  const ternary = <span className="badge" style={{ color: kitSpacing ? border : 'var(--text-primary)' }}>{appClass}</span>;
  return <a href={href} title={String(ternary)} id={anchor} style={style} onClick={() => confirmDelete({ title: 'Delete the schedule?' })}>Open</a>;
}
