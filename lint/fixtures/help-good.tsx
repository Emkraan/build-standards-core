// The same controls written the way the help layer rules ask. No finding in this file.
import { Button, IconButton } from '@example/kit';
import { IconTrash } from '@example/kit';

export function Toolbar({ valid, busy, onRemove, props }: { valid: boolean; busy: boolean; onRemove: () => void; props: object }) {
  return (
    <div>
      <Button disabledReason={valid ? undefined : 'Fill in the name to save.'}>Save</Button>
      <Button disabled={busy} loading={busy}>Saving</Button>
      <Button disabled={false}>Always on</Button>
      <Button {...props} disabled>Spread can carry a reason</Button>
      <IconButton label="Remove host" icon={<IconTrash />} disabledReason="Drain the sessions first." />
      <Button icon={<IconTrash />} aria-label="Remove host" data-tip="Remove host" onClick={onRemove} />
      <Button icon={<IconTrash />} onClick={onRemove}>Remove</Button>
      <button type="button" aria-label="Remove host" title="Remove host" onClick={onRemove}>
        <IconTrash />
      </button>
      <button type="button" onClick={onRemove}>
        <IconTrash /> Remove
      </button>
      <span data-tip="A group of session hosts that share one image and one schedule.">Pool</span>
      <span data-tip={`Updated ${busy ? 'now' : 'a while ago'}`}>Dynamic tips are not measured</span>
      <Button disabledReason="You need the Operator role. Ask an owner." onClick={onRemove}>Remove</Button>
    </div>
  );
}
