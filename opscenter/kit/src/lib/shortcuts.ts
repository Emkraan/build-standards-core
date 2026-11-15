/* Keyboard shortcut registry. Components register what they listen for so the help sheet (opened
   with ?) lists every shortcut on the page. A registration without a handler is display-only: the
   component keeps its own listener (the rail's [ and the palette's Cmd or Ctrl and K). */

import { createContext, useContext, useEffect, useRef } from 'react';
import { isMacLike } from './env';

export interface ShortcutDef {
  /** Unique id. Registering the same id again replaces the earlier entry. */
  id: string;
  /**
   * Keys in a small grammar: `mod+k` (Cmd on macOS, Ctrl elsewhere), `shift+d`, `?`, `[`, or a
   * two-key sequence separated by a space, `g h`.
   */
  keys: string;
  description: string;
  group?: string | undefined;
  /** Runs when the keys are pressed. Omit for a display-only entry. */
  handler?: ((event: KeyboardEvent) => void) | undefined;
  /** Also fire while the user is typing in a field (default false). */
  allowInInput?: boolean | undefined;
}

export interface ShortcutRegistry {
  register: (def: ShortcutDef) => () => void;
}

export const ShortcutContext = createContext<ShortcutRegistry | null>(null);

/** Registers a shortcut for as long as the component is mounted. A no-op outside ShortcutLayer. */
export function useShortcut(def: ShortcutDef | null): void {
  const registry = useContext(ShortcutContext);
  const ref = useRef(def);
  ref.current = def;
  const id = def?.id;
  const keys = def?.keys;
  const description = def?.description;
  const group = def?.group;
  const hasHandler = Boolean(def?.handler);
  const allowInInput = def?.allowInInput;
  useEffect(() => {
    if (!registry || !id || !keys || description === undefined) return undefined;
    return registry.register({
      id,
      keys,
      description,
      group,
      allowInInput,
      handler: hasHandler ? (event) => ref.current?.handler?.(event) : undefined,
    });
  }, [registry, id, keys, description, group, hasHandler, allowInInput]);
}

interface Combo {
  key: string;
  mod: boolean;
  shift: boolean;
  alt: boolean;
}

/** Parses `mod+shift+k` or `g h` into a list of key combos. */
export function parseKeys(keys: string): Combo[] {
  return keys
    .trim()
    .split(/\s+/)
    .map((part) => {
      const tokens = part.toLowerCase().split('+');
      const key = tokens[tokens.length - 1] ?? '';
      return {
        key: key === '' && part.endsWith('+') ? '+' : key,
        mod: tokens.includes('mod') || tokens.includes('ctrl') || tokens.includes('cmd'),
        shift: tokens.slice(0, -1).includes('shift'),
        alt: tokens.includes('alt'),
      };
    });
}

/** True when a key event matches one combo. Printable symbols ignore Shift (? is Shift and /). */
export function matchesCombo(event: KeyboardEvent, combo: Combo): boolean {
  const key = event.key.toLowerCase();
  if (key !== combo.key) return false;
  const mod = event.metaKey || event.ctrlKey;
  if (mod !== combo.mod || event.altKey !== combo.alt) return false;
  const symbol = combo.key.length === 1 && !/[a-z0-9]/.test(combo.key);
  return symbol || event.shiftKey === combo.shift;
}

/** Display text for one combo, for example `Cmd K` or `Ctrl Shift D`. */
export function comboLabel(combo: Combo): string[] {
  const parts: string[] = [];
  if (combo.mod) parts.push(isMacLike() ? 'Cmd' : 'Ctrl');
  if (combo.alt) parts.push(isMacLike() ? 'Option' : 'Alt');
  if (combo.shift) parts.push('Shift');
  const k = combo.key;
  parts.push(k.length === 1 ? k.toUpperCase() : k.charAt(0).toUpperCase() + k.slice(1));
  return parts;
}
