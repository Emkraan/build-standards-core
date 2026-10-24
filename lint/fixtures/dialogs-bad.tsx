// An alias binds ask, not confirm, so the bare confirm below is native. window.* is always native.
import { useConfirm, usePrompt } from './kit';
export function Mixed() {
  const { confirm: ask, dialog } = useConfirm();
  const { prompt } = usePrompt();
  const run = async () => {
    await ask({ title: 'Sure?' });
    if (confirm('Really?')) { window.prompt('Name?'); }
    await prompt({ title: 'Name?' });
  };
  return <div onClick={run}>{dialog}</div>;
}
