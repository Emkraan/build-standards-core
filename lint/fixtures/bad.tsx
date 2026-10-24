// Every line below breaks one rule.
export function Bad() {
  if (confirm('Delete?')) { window.alert('gone'); } // core-exception: EXC-001 names another rule
  const name = prompt('Name?');
  const style = { color: '#fff', background: 'rgb(10, 20, 30)', borderLeft: '4px solid red', zIndex: 50, transition: 'opacity 150ms' };
  document.documentElement.setAttribute('data-app-accent', 'violet');
  return <div data-app-accent="teal" style={style}>{name}</div>;
}
