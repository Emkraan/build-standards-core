/* Glossary: an app registers the words its screens use once, and <Term id> shows a word anywhere
   with its short meaning one hover or one focus away. The long text and link of an entry are for
   InfoTip. An id that is not registered shows plain text. */

import { createContext, useContext, useEffect, useMemo } from 'react';
import type { HTMLAttributes, ReactNode } from 'react';
import { cx, devWarn } from '../lib/env';
import { joinIds, useTip } from './Tooltip';
import type { TipSide } from './Tooltip';

export interface GlossaryEntry {
  /** The word as it reads in a sentence ("host pool"). */
  term: string;
  /** One or two short plain sentences. This is the tip. */
  short: string;
  /** The longer explanation, for InfoTip. */
  long?: string | undefined;
  /** Where the full documentation lives. */
  href?: string | undefined;
}

/** Glossary entries by id. */
export type Glossary = Readonly<Record<string, GlossaryEntry>>;

const EMPTY: Glossary = Object.freeze({});
const GlossaryContext = createContext<Glossary>(EMPTY);

export interface GlossaryProviderProps {
  glossary: Glossary;
  children?: ReactNode;
}

/** Registers a glossary for everything below it. A provider inside another one adds to it and wins on a shared id. */
export function GlossaryProvider({ glossary, children }: GlossaryProviderProps) {
  const parent = useContext(GlossaryContext);
  const merged = useMemo<Glossary>(() => (parent === EMPTY ? glossary : { ...parent, ...glossary }), [parent, glossary]);
  return <GlossaryContext.Provider value={merged}>{children}</GlossaryContext.Provider>;
}

/** The glossary in scope, empty outside a GlossaryProvider. */
export function useGlossary(): Glossary {
  return useContext(GlossaryContext);
}

/** One entry by id, or undefined when it is not registered. */
export function glossaryEntry(glossary: Glossary, id: string): GlossaryEntry | undefined {
  return Object.prototype.hasOwnProperty.call(glossary, id) ? glossary[id] : undefined;
}

export interface TermProps extends Omit<HTMLAttributes<HTMLElement>, 'id' | 'children'> {
  /** The glossary id. */
  id: string;
  /** The words to show when they differ from the entry's term ("host pools"). */
  children?: ReactNode;
  tipSide?: TipSide | undefined;
}

/**
 * A domain word with a dotted underline. Its short meaning is the tip and its description, and the word is
 * keyboard focusable so the tip shows on focus too. Use it for the first appearance of a word on a page.
 * An id missing from the glossary renders the words as plain text and warns in development only.
 */
export function Term({ id, children, tipSide, className, ...rest }: TermProps) {
  const entry = glossaryEntry(useGlossary(), id);
  const { props: tip, description } = useTip(entry?.short, tipSide);
  useEffect(() => {
    if (!entry) devWarn(`term:${id}`, `<Term id="${id}"> is not in the glossary. It renders as plain text.`);
  }, [entry, id]);
  if (!entry) return <>{children ?? id}</>;
  return (
    <span
      {...rest}
      {...tip}
      aria-describedby={joinIds(rest['aria-describedby'], tip['aria-describedby'])}
      className={cx('term', className)}
      tabIndex={rest.tabIndex ?? 0}
    >
      {children ?? entry.term}
      {description}
    </span>
  );
}
