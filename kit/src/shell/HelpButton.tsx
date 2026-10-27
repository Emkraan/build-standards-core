/* HelpButton: opens the help drawer. Header shows it while the page on screen registered help. */

import { IconHelp } from '../icons/icons';
import { Button } from '../primitives/Button';
import { useHelp } from './help';

export interface HelpButtonProps {
  label?: string | undefined;
}

/**
 * The Help button. It renders only while the page on screen registered help, so a page without help
 * shows no button. Header shows it by default. Put it elsewhere to place it yourself.
 */
export function HelpButton({ label = 'Help' }: HelpButtonProps) {
  const help = useHelp();
  if (!help?.page) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      className="help-btn"
      icon={<IconHelp />}
      aria-haspopup="dialog"
      aria-expanded={help.open}
      onClick={() => help.setOpen(!help.open)}
    >
      {label}
    </Button>
  );
}
