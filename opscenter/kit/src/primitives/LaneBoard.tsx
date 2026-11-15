import { useRef, useState } from 'react';
import type { ReactNode } from 'react';

export interface LaneBoardCard {
  id: string;
  /** Plain text name, used in the spoken announcements. */
  label: string;
}

export interface LaneBoardLane<T extends LaneBoardCard = LaneBoardCard> {
  id: string;
  label: string;
  cards: readonly T[];
}

export interface LaneBoardMove {
  cardId: string;
  from: string;
  to: string;
  /** Position in the target lane after the move (0 based). */
  index: number;
}

export interface LaneBoardProps<T extends LaneBoardCard = LaneBoardCard> {
  lanes: readonly LaneBoardLane<T>[];
  /** Called once per completed move. The board never reorders itself: the host updates `lanes`. */
  onMove: (move: LaneBoardMove) => void;
  renderCard?: (card: T) => ReactNode;
  /** Shown in a lane with no cards. */
  emptyText?: string;
  label?: string;
  /** Sizes the board to the window with a floor (a short window never traps the page): the board is the window height
      less room for the page header, never shorter than 360px, scrolls sideways on its own edge and each
      lane scrolls vertically on its own. Use it inside a page that is one vertical scroll container
      (`page-scroll`). Default false: the board is as tall as its tallest lane. */
  fit?: boolean;
}

interface Pick {
  cardId: string;
  from: string;
  to: string;
  index: number;
}

/**
 * A lane board: lanes as columns, cards inside. Drag a card with the pointer, or focus it and press
 * Space or Enter to pick it up, the arrow keys to choose a lane (left, right) and a position (up, down),
 * Space or Enter to drop and Escape to cancel. Each step is announced in a polite live region.
 * Which moves are allowed and what a lane means stay in the app.
 */
export function LaneBoard<T extends LaneBoardCard = LaneBoardCard>({
  lanes,
  onMove,
  renderCard,
  emptyText = 'No cards',
  label = 'Board',
  fit = false,
}: LaneBoardProps<T>) {
  const [drag, setDrag] = useState<string | null>(null);
  const [over, setOver] = useState<{ lane: string; index: number } | null>(null);
  const [pick, setPick] = useState<Pick | null>(null);
  const [said, setSaid] = useState('');
  const refs = useRef(new Map<string, HTMLElement>());

  const laneOf = (cardId: string) => lanes.find((l) => l.cards.some((c) => c.id === cardId));
  const nameOf = (id: string) => lanes.find((l) => l.id === id)?.label ?? id;

  const finish = (cardId: string, to: string, index: number) => {
    const from = laneOf(cardId)?.id;
    if (!from) return;
    const fromIdx = (laneOf(cardId)?.cards ?? []).findIndex((c) => c.id === cardId);
    if (from === to && (index === fromIdx || index === fromIdx + 1)) return;
    // A same lane drop index counts the card itself; the reported index is after removal.
    const adj = from === to && index > fromIdx ? index - 1 : index;
    onMove({ cardId, from, to, index: adj });
  };

  const describe = (p: Pick) => {
    const card = laneOf(p.cardId)?.cards.find((c) => c.id === p.cardId);
    const count = lanes.find((l) => l.id === p.to)?.cards.filter((c) => c.id !== p.cardId).length ?? 0;
    return `${card?.label ?? 'Card'}, ${nameOf(p.to)}, position ${p.index + 1} of ${count + 1}`;
  };

  const onKey = (e: React.KeyboardEvent<HTMLElement>, card: T, lane: LaneBoardLane<T>, idx: number) => {
    if (e.target !== e.currentTarget) return;
    if (!pick) {
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        const p = { cardId: card.id, from: lane.id, to: lane.id, index: idx };
        setPick(p);
        setSaid(`Picked up ${describe(p)}. Arrow keys move, Space drops, Escape cancels.`);
      }
      return;
    }
    const li = lanes.findIndex((l) => l.id === pick.to);
    const size = (id: string) => (lanes.find((l) => l.id === id)?.cards ?? []).filter((c) => c.id !== pick.cardId).length;
    let next: Pick | null = null;
    if (e.key === 'ArrowRight' && li < lanes.length - 1) {
      const to = lanes[li + 1]!.id;
      next = { ...pick, to, index: Math.min(pick.index, size(to)) };
    } else if (e.key === 'ArrowLeft' && li > 0) {
      const to = lanes[li - 1]!.id;
      next = { ...pick, to, index: Math.min(pick.index, size(to)) };
    } else if (e.key === 'ArrowDown' && pick.index < size(pick.to)) {
      next = { ...pick, index: pick.index + 1 };
    } else if (e.key === 'ArrowUp' && pick.index > 0) {
      next = { ...pick, index: pick.index - 1 };
    }
    if (next) {
      e.preventDefault();
      setPick(next);
      setSaid(`Move to ${describe(next)}`);
    } else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      const origin = laneOf(pick.cardId)!;
      const same = pick.to === origin.id && pick.index === origin.cards.findIndex((c) => c.id === pick.cardId);
      setSaid(same ? `Dropped ${describe(pick)}, no change` : `Dropped ${describe(pick)}`);
      if (!same) {
        const rest = (lanes.find((l) => l.id === pick.to)?.cards ?? []).filter((c) => c.id !== pick.cardId);
        onMove({ cardId: pick.cardId, from: origin.id, to: pick.to, index: Math.min(pick.index, rest.length) });
      }
      setPick(null);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setSaid(`Cancelled, ${card.label} stays in ${nameOf(pick.from)}`);
      setPick(null);
    }
  };

  return (
    <div className="lane-board" role="group" aria-label={label} data-fit={fit ? '' : undefined}>
      {lanes.map((lane) => {
        const dropIdx = (over?.lane === lane.id ? over.index : pick?.to === lane.id ? pick.index : -1);
        const others = lane.cards.filter((c) => !(pick && c.id === pick.cardId)).length;
        const showPickAt = pick?.to === lane.id;
        return (
          <section
            key={lane.id}
            className="lane-board-lane"
            aria-label={`${lane.label}, ${lane.cards.length} ${lane.cards.length === 1 ? 'card' : 'cards'}`}
            data-over={over?.lane === lane.id || showPickAt ? '' : undefined}
            onDragOver={(e) => {
              if (!drag) return;
              e.preventDefault();
              const cards = Array.from((e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('[data-card-id]'));
              let index = cards.length;
              for (let i = 0; i < cards.length; i++) {
                const r = cards[i]!.getBoundingClientRect();
                if (e.clientY < r.top + r.height / 2) { index = i; break; }
              }
              setOver((o) => (o && o.lane === lane.id && o.index === index ? o : { lane: lane.id, index }));
            }}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(null);
            }}
            onDrop={(e) => {
              e.preventDefault();
              const id = e.dataTransfer?.getData('text/plain') || drag;
              const index = over?.lane === lane.id ? over.index : lane.cards.length;
              setDrag(null);
              setOver(null);
              if (id) finish(id, lane.id, index);
            }}
          >
            <h3 className="lane-board-head">
              <span>{lane.label}</span>
              <span className="lane-board-count">{lane.cards.length}</span>
            </h3>
            <ul className="lane-board-cards">
              {lane.cards.length === 0 && !showPickAt && (
                <li className="lane-board-empty">{emptyText}</li>
              )}
              {lane.cards.map((card, idx) => {
                const picked = pick?.cardId === card.id;
                const slot = lane.cards.slice(0, idx).filter((c) => c.id !== pick?.cardId).length;
                return (
                  <li key={card.id} className="lane-board-slot" data-picked={picked ? '' : undefined}>
                    {!picked && dropIdx === slot && <div className="lane-board-drop" aria-hidden="true" />}
                    <div
                      ref={(el) => { if (el) refs.current.set(card.id, el); else refs.current.delete(card.id); }}
                      className="lane-board-card"
                      data-card-id={card.id}
                      data-dragging={drag === card.id ? '' : undefined}
                      tabIndex={0}
                      draggable
                      aria-roledescription="draggable card"
                      onDragStart={(e) => {
                        e.dataTransfer?.setData('text/plain', card.id);
                        if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
                        setDrag(card.id);
                      }}
                      onDragEnd={() => { setDrag(null); setOver(null); }}
                      onKeyDown={(e) => onKey(e, card, lane, idx)}
                      onBlur={() => { if (pick?.cardId === card.id) { setPick(null); setSaid(`Cancelled, ${card.label} stays in ${nameOf(pick.from)}`); } }}
                    >
                      {renderCard ? renderCard(card) : card.label}
                    </div>
                  </li>
                );
              })}
              {dropIdx >= others && (over?.lane === lane.id || showPickAt) && (
                <li className="lane-board-slot"><div className="lane-board-drop" aria-hidden="true" /></li>
              )}
            </ul>
          </section>
        );
      })}
      <span className="kit-sr-only" role="status" aria-live="polite">{said}</span>
    </div>
  );
}
