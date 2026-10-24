// The kit hooks bind confirm and prompt locally, so none of these calls is a native dialog.
import { useConfirm, usePrompt } from './kit';
export function Dialogs() {
  const { confirm, dialog } = useConfirm();
  const { confirm: ask } = useConfirm();
  const { prompt, dialog: promptDialog } = usePrompt();
  const run = async () => {
    if (await confirm({ title: 'Delete the schedule?' })) { await prompt({ title: 'Name?' }); }
    await ask({ title: 'Sure?' });
  };
  return <div onClick={run}>{dialog}{promptDialog}</div>;
}
