// Controls the help layer rules reject. UI011 flags a kit Button that is disabled and gives no reason
// (two of them), UI012 flags a control that is only an icon with no name or no tip (four of them), and
// UI013 flags a tip written as a literal that is too long (two of them).
import { Button, IconButton } from '@example/kit';
import { IconTrash } from '@example/kit';

export function Toolbar({ valid, busy, onRemove }: { valid: boolean; busy: boolean; onRemove: () => void }) {
  return (
    <div>
      <Button disabled={!valid}>Save</Button>
      <IconButton label="Remove" icon={<IconTrash />} disabled />
      <Button icon={<IconTrash />} onClick={onRemove} />
      <Button icon={<IconTrash />} aria-label="Remove host" onClick={onRemove} />
      <button type="button" onClick={onRemove}>
        <IconTrash />
      </button>
      <button type="button" aria-label="Remove host" onClick={onRemove}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2h12v12H2z" /></svg>
      </button>
      <span data-tip="A host pool is a group of session hosts that share one image, one scaling plan and one set of settings, and that users are assigned to as a unit. Create one for each team that needs its own image and its own schedule of working hours.">Pool</span>
      <Button disabledReason="You need the Operator role. Ask an owner. Then reload the page." onClick={onRemove}>Remove</Button>
    </div>
  );
}
