/* HelpDrawer: the help of the page on screen in a side sheet, opened by the Help button in the header
   (HelpButton) or from the command palette (useHelpPaletteItems). The page writes its help once with
   usePageHelp. The drawer is a Modal sheet, so focus, Escape, the scroll lock and the layer stack work
   as in every other dialog. AppShell mounts it, so an app does not. */

import { useMemo } from 'react';
import type { PaletteItem } from '../chrome/CommandPalette';
import { IconHelp } from '../icons/icons';
import { devWarn } from '../lib/env';
import { Modal, ModalSection } from '../overlays/Modal';
import { glossaryEntry, useGlossary } from '../primitives/Glossary';
import { HelpLink } from '../primitives/HelpLink';
import { useHelp } from './help';

export interface HelpDrawerProps {
  /** Heading prefix: "Help: <page title>". */
  label?: string | undefined;
  closeLabel?: string | undefined;
  stepsHeading?: string | undefined;
  termsHeading?: string | undefined;
  linksHeading?: string | undefined;
}

/** The drawer. AppShell mounts one, so an app does not. Renders nothing while no page registered help. */
export function HelpDrawer({
  label = 'Help',
  closeLabel = 'Close help',
  stepsHeading = 'How to',
  termsHeading = 'Words on this page',
  linksHeading = 'Learn more',
}: HelpDrawerProps) {
  const help = useHelp();
  const glossary = useGlossary();
  const page = help?.page ?? null;
  const terms = useMemo(() => {
    const found = [];
    for (const id of page?.terms ?? []) {
      const entry = glossaryEntry(glossary, id);
      if (entry) found.push({ id, entry });
      else devWarn(`help-term:${id}`, `page help lists the term "${id}", which is not in the glossary. The drawer skips it.`);
    }
    return found;
  }, [page, glossary]);
  if (!help || !page) return null;
  return (
    <Modal
      open={help.open}
      onClose={() => help.setOpen(false)}
      title={`${label}: ${page.title}`}
      subtitle={page.summary}
      variant="sheet"
      size="md"
      footer={null}
      closeLabel={closeLabel}
      className="help-drawer"
    >
      {page.steps && page.steps.length > 0 ? (
        <ModalSection title={stepsHeading}>
          <ol className="help-steps">
            {page.steps.map((step, i) => (
              <li key={`${i}-${step}`}>{step}</li>
            ))}
          </ol>
        </ModalSection>
      ) : null}
      {terms.length > 0 ? (
        <ModalSection title={termsHeading}>
          <dl className="help-terms">
            {terms.map(({ id, entry }) => (
              <div key={id} className="help-term">
                <dt>{entry.term}</dt>
                <dd>
                  {entry.long ?? entry.short}
                  {entry.href ? (
                    <>
                      {' '}
                      <HelpLink href={entry.href}>Learn more</HelpLink>
                    </>
                  ) : null}
                </dd>
              </div>
            ))}
          </dl>
        </ModalSection>
      ) : null}
      {page.links && page.links.length > 0 ? (
        <ModalSection title={linksHeading}>
          <ul className="help-links">
            {page.links.map((link) => (
              <li key={`${link.href}-${link.label}`}>
                <HelpLink href={link.href}>{link.label}</HelpLink>
              </li>
            ))}
          </ul>
        </ModalSection>
      ) : null}
    </Modal>
  );
}

export interface HelpPaletteOptions {
  /** Palette group the items sit in. Default "Help". */
  group?: string | undefined;
}

/**
 * Command palette items for the help of the page on screen: one for the page and one for each word it
 * lists. Choosing any of them opens the help drawer. The palette takes its items as a prop, so merge these
 * into yours: `items={[...navItems, ...useHelpPaletteItems()]}`. Empty while no page registered help.
 */
export function useHelpPaletteItems({ group = 'Help' }: HelpPaletteOptions = {}): PaletteItem[] {
  const help = useHelp();
  const glossary = useGlossary();
  const page = help?.page ?? null;
  const setOpen = help?.setOpen;
  return useMemo(() => {
    if (!page || !setOpen) return [];
    const open = () => setOpen(true);
    const items: PaletteItem[] = [
      {
        id: 'help:page',
        label: `Help: ${page.title}`,
        kind: 'Help',
        group,
        description: page.summary,
        keywords: ['help', 'how to', 'guide'],
        icon: <IconHelp />,
        onSelect: open,
      },
    ];
    for (const id of page.terms ?? []) {
      const entry = glossaryEntry(glossary, id);
      if (!entry) continue;
      items.push({
        id: `help:term:${id}`,
        label: entry.term,
        kind: 'Term',
        group,
        description: entry.short,
        keywords: ['help', 'what is', 'meaning', id],
        icon: <IconHelp />,
        onSelect: open,
      });
    }
    return items;
  }, [page, glossary, group, setOpen]);
}
