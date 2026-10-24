/* SearchInput: an inline filter field with a focus glow, an icon that takes the accent on focus and
   a clear button. Controlled by value and onChange. focusHotkey (for example "/") focuses it from
   anywhere, the way a search-first tool should, and is ignored while typing in another field. For
   the global command search use SearchTrigger and the palette instead. */

import { type InputHTMLAttributes, useEffect, useRef, useState } from 'react';
import { IconClose, IconSearch } from '../icons/icons';
import { cx } from '../lib/env';

export interface SearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> {
  value: string;
  onChange: (value: string) => void;
  /** A single key that focuses the field from document scope, for example "/". */
  focusHotkey?: string | undefined;
}

export function SearchInput({ value, onChange, placeholder = 'Search', focusHotkey, className, ...rest }: SearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focus, setFocus] = useState(false);

  useEffect(() => {
    if (!focusHotkey) return undefined;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== focusHotkey || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      e.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [focusHotkey]);

  return (
    <div className={cx('search-field', className)} data-focus={focus ? 'true' : undefined}>
      <IconSearch size={14} />
      <input
        aria-label={placeholder}
        {...rest}
        ref={inputRef}
        type="search"
        className="search-field-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        placeholder={placeholder}
      />
      {value ? (
        <button type="button" className="search-field-clear" onClick={() => onChange('')} aria-label="Clear search">
          <IconClose size={12} />
        </button>
      ) : null}
    </div>
  );
}
