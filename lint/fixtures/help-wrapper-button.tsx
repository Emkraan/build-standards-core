// A Button imported by a relative path is the project's own wrapper (or a part inside the kit itself), so
// UI011 and UI012 leave it alone. Only an import from the kit package or alias counts as the kit's Button.
import { Button } from './ui/Button';
import { IconTrash } from '@example/kit';

export function Wrapped({ onRemove }: { onRemove: () => void }) {
  return (
    <div>
      <Button disabled>Own wrapper</Button>
      <Button icon={<IconTrash />} onClick={onRemove} />
    </div>
  );
}
