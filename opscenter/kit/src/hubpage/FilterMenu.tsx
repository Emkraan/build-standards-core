/* FilterMenu: the one way a third level becomes a control. A button (with the picked value in its
   label) that opens a popover listing the options, each with its live count. Single choice, and the
   `allValue` option clears the filter. */

import { useRef, useState } from 'react';
import { IconChevronDown } from '../icons/icons';
import { Popover } from '../overlays/Popover';
import { Button } from '../primitives/Button';

export interface FilterMenuOption {
  value: string;
  label: string;
  count?: number | undefined;
}

export interface FilterMenuProps {
  /** The button label, for example "Lane". */
  label: string;
  options: readonly FilterMenuOption[];
  value: string;
  /** The value that means no filter (the first option). */
  allValue: string;
  onChange: (value: string) => void;
  tip?: string | undefined;
}

export function FilterMenu({ label, options, value, allValue, onChange, tip }: FilterMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLButtonElement | null>(null);
  const active = value !== allValue;
  const current = options.find((o) => o.value === value);
  return (
    <>
      <Button
        ref={ref}
        size="sm"
        variant="secondary"
        className="hp-filter"
        aria-haspopup="dialog"
        aria-expanded={open}
        data-active={active ? '' : undefined}
        data-tip={tip}
        onClick={() => setOpen((o) => !o)}
      >
        {active && current ? `${label}: ${current.label}` : label}
        <IconChevronDown size={12} />
      </Button>
      <Popover open={open} onClose={() => setOpen(false)} anchorRef={ref} label={`${label} filter`} role="dialog" placement="bottom-start">
        <div className="hp-filter-menu" role="group" aria-label={`${label} options`}>
          {options.map((o) => (
            <button
              key={o.value}
              type="button"
              className="hp-filter-opt"
              aria-pressed={o.value === value}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
            >
              <span className="hp-filter-name">{o.label}</span>
              {o.count !== undefined ? <span className="hp-filter-n">{o.count}</span> : null}
            </button>
          ))}
        </div>
      </Popover>
    </>
  );
}
