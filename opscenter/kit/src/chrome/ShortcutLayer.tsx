/* ShortcutLayer: the keyboard shortcut registry and its help dialog, opened with ? outside text
   fields. Components register with useShortcut. Entries with a handler fire here, and display-only
   entries (the rail's [ and the palette's Cmd or Ctrl and K) are listed for discovery. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { isDialogOpen } from '../lib/layers';
import { isTypingTarget } from '../lib/env';
import { ShortcutContext, comboLabel, matchesCombo, parseKeys } from '../lib/shortcuts';
import type { ShortcutDef, ShortcutRegistry } from '../lib/shortcuts';
import { SEQUENCE_TIMEOUT } from '../lib/timing';
import { Modal } from '../overlays/Modal';
import { Kbd } from '../primitives/marks';

export interface ShortcutLayerProps {
  children?: ReactNode;
  /** Title of the help dialog. */
  title?: string | undefined;
}

export function ShortcutLayer({ children, title = 'Keyboard shortcuts' }: ShortcutLayerProps) {
  const defs = useRef(new Map<string, ShortcutDef>());
  const [version, setVersion] = useState(0);
  const [helpOpen, setHelpOpen] = useState(false);
  const pending = useRef<{ id: string; step: number; at: number }[]>([]);

  const register = useCallback((def: ShortcutDef) => {
    defs.current.set(def.id, def);
    setVersion((v) => v + 1);
    return () => {
      if (defs.current.get(def.id) === def) {
        defs.current.delete(def.id);
        setVersion((v) => v + 1);
      }
    };
  }, []);

  const registry = useMemo<ShortcutRegistry>(() => ({ register }), [register]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      const typing = isTypingTarget(event.target);
      if (event.key === '?' && !typing && !isDialogOpen() && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        setHelpOpen(true);
        return;
      }
      if (isDialogOpen()) return;
      const now = Date.now();
      // Second keys of sequences that are already under way.
      const live = pending.current.filter((p) => now - p.at < SEQUENCE_TIMEOUT);
      pending.current = [];
      for (const p of live) {
        const def = defs.current.get(p.id);
        const combos = def ? parseKeys(def.keys) : [];
        const combo = combos[p.step];
        if (!def || !combo || (typing && !def.allowInInput) || !matchesCombo(event, combo)) continue;
        if (p.step === combos.length - 1) {
          event.preventDefault();
          def.handler?.(event);
          return;
        }
        pending.current.push({ id: p.id, step: p.step + 1, at: now });
      }
      for (const def of defs.current.values()) {
        if (!def.handler || (typing && !def.allowInInput)) continue;
        const combos = parseKeys(def.keys);
        const first = combos[0];
        if (!first || !matchesCombo(event, first)) continue;
        if (combos.length === 1) {
          event.preventDefault();
          def.handler(event);
          return;
        }
        pending.current.push({ id: def.id, step: 1, at: now });
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const groups = useMemo(() => {
    const out = new Map<string, ShortcutDef[]>();
    const all: ShortcutDef[] = [...defs.current.values(), { id: 'kit.help', keys: '?', description: 'Show keyboard shortcuts', group: 'General' }];
    for (const def of all) {
      const g = def.group ?? 'General';
      out.set(g, [...(out.get(g) ?? []), def]);
    }
    return [...out.entries()];
    // version changes whenever the registry changes.
  }, [version, helpOpen]);

  return (
    <ShortcutContext.Provider value={registry}>
      {children}
      <Modal open={helpOpen} onClose={() => setHelpOpen(false)} title={title} size="md" cancelLabel={null} footer={null}>
        <div className="shortcut-groups">
          {groups.map(([group, list]) => (
            <section key={group} className="shortcut-group" aria-label={group}>
              <h3 className="shortcut-group-title">{group}</h3>
              <dl className="shortcut-list">
                {list.map((def) => (
                  <div key={def.id} className="shortcut-row">
                    <dt className="shortcut-desc">{def.description}</dt>
                    <dd className="shortcut-keys">
                      {parseKeys(def.keys).map((combo, i) => (
                        <span key={i} className="shortcut-combo">
                          {i > 0 ? <span className="shortcut-then">then</span> : null}
                          {comboLabel(combo).map((k) => (
                            <Kbd key={k}>{k}</Kbd>
                          ))}
                        </span>
                      ))}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </Modal>
    </ShortcutContext.Provider>
  );
}
