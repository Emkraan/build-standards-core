/* An art mark: a picture with a glow behind it and a layered effect on top. Three layers sit in one
   box: the glow, the picture and the effect layer (the recipe picked by `effect`, see effects.ts and
   the art mark section of styles/kit.css). The effect layers stay hidden until a host turns them on,
   so a mark in a plain context is a still picture. A host is any ancestor that carries
   data-art-host. It turns the effect on with data-art-live (an empty value for the normal level,
   "soft" for a calmer one) and on :hover and :focus-visible, which also raise the level.
   Only transform, opacity and filter animate, every duration is a kit token times a plain factor,
   the effect pauses while the mark is off screen or the tab is hidden, and under
   prefers-reduced-motion nothing moves. */

import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, RefObject } from 'react';
import { ART_EFFECTS, artEffectFor } from './effects';

/** Pauses the effect layers while the mark is off screen or the document is hidden. */
export function useArtPaused(ref: RefObject<HTMLElement | null>): boolean {
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let visible = true;
    const update = () => setPaused(document.visibilityState === 'hidden' || !visible);
    let io: IntersectionObserver | undefined;
    if (typeof IntersectionObserver === 'function') {
      io = new IntersectionObserver((entries) => {
        // The latest entry for the mark decides: a batch can hold an old entry before the newest one.
        const latest = entries[entries.length - 1];
        if (latest) visible = latest.isIntersecting;
        update();
      });
      io.observe(el);
    }
    document.addEventListener('visibilitychange', update);
    // A tab that is already hidden at mount gets no visibilitychange event, so read it once now.
    update();
    return () => {
      io?.disconnect();
      document.removeEventListener('visibilitychange', update);
    };
  }, [ref]);
  return paused;
}

/** Positions in percent of the mark box (0 to 100, from the top left), measured on the trimmed picture. */
export interface ArtAnchors {
  /** The point the effect grows from. */
  focus?: readonly [number, number];
  /** The furthest distance of the effect from the focus. */
  reach?: number;
  /** Where an occasional spark appears. */
  spark?: readonly [number, number];
  /** The point the picture shakes around. */
  pivot?: readonly [number, number];
  /** Radii in percent of the box, and the start angle and width of the arc wedge in degrees (clockwise from straight up). */
  arcs?: { radii: readonly number[]; from: number; span: number };
  /** x, y, width and height of a window a bar crosses. */
  box?: readonly [number, number, number, number];
  /** The part of the picture that slides (x, y, width, height) and how far it slides (x and y, percent of the box). */
  feed?: { rect: readonly [number, number, number, number]; slide: readonly [number, number] };
}

const isNum = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
const pct = (n: number) => `${n}%`;

/** The CSS custom properties that carry the anchors to the recipes. Non-finite numbers are skipped, and a feed window with no width or height is dropped. */
export function artAnchorVars(a: ArtAnchors): Record<string, string | number> {
  const v: Record<string, string | number> = {};
  if (a.focus && isNum(a.focus[0]) && isNum(a.focus[1])) {
    v['--am-fx-x'] = pct(a.focus[0]);
    v['--am-fx-y'] = pct(a.focus[1]);
  }
  if (isNum(a.reach)) v['--am-reach'] = a.reach;
  if (a.spark && isNum(a.spark[0]) && isNum(a.spark[1])) {
    v['--am-sp-x'] = pct(a.spark[0]);
    v['--am-sp-y'] = pct(a.spark[1]);
  }
  if (a.pivot && isNum(a.pivot[0]) && isNum(a.pivot[1])) v['--am-pivot'] = `${a.pivot[0]}% ${a.pivot[1]}%`;
  if (a.arcs && isNum(a.arcs.from) && isNum(a.arcs.span)) {
    v['--am-arc-from'] = `${a.arcs.from}deg`;
    v['--am-arc-span'] = `${a.arcs.span}deg`;
    a.arcs.radii.forEach((r, i) => {
      if (isNum(r)) v[`--am-r${i}`] = r;
    });
  }
  if (a.box && a.box.every(isNum)) {
    v['--am-bx'] = pct(a.box[0]);
    v['--am-by'] = pct(a.box[1]);
    v['--am-bw'] = pct(a.box[2]);
    v['--am-bh'] = pct(a.box[3]);
  }
  if (a.feed && a.feed.rect.every(isNum) && a.feed.slide.every(isNum)) {
    const [x, y, w, h] = a.feed.rect;
    // The inner picture is scaled by 1 / width and 1 / height, so a window with no area cannot be drawn.
    if (w > 0 && h > 0) {
      v['--am-fdx'] = pct(x);
      v['--am-fdy'] = pct(y);
      v['--am-fdw'] = pct(w);
      v['--am-fdh'] = pct(h);
      v['--am-fd-ix'] = pct((-x / w) * 100);
      v['--am-fd-iy'] = pct((-y / h) * 100);
      v['--am-fd-iw'] = pct((100 / w) * 100);
      v['--am-fd-ih'] = pct((100 / h) * 100);
      v['--am-slide-x'] = pct(a.feed.slide[0]);
      v['--am-slide-y'] = pct(a.feed.slide[1]);
    }
  }
  return v;
}

const HUE_TOKEN = /^[a-z][a-z0-9-]*$/;
const DEFAULT_HUE = 'blue';
const MIN_SIZE = 1;
const MAX_SIZE = 1024;
const MAX_INTENSITY = 3;
// Characters that could close the url("...") string or its function, or that a URL never holds.
const UNSAFE_SRC = /["'()\\\u0000-\u001f\u007f]/;

/** True when the hue is a plain token name that is safe inside var(--hue-NAME). */
export function isArtHue(hue: unknown): hue is string {
  return typeof hue === 'string' && HUE_TOKEN.test(hue);
}

/** True when the picture address can sit inside a quoted CSS url() with no way out of it. */
export function isArtSrcSafe(src: unknown): src is string {
  return typeof src === 'string' && src.length > 0 && !UNSAFE_SRC.test(src);
}

export interface ArtMarkProps {
  /** The picture. An address with a quote, parenthesis, backslash or control character still shows as a plain image but is kept out of the CSS mask, so the sheen and slide layers are hidden. Expects a transparent, trimmed, square image (256 px, with a 128 px copy for marks of 40 px or less picked by the caller). */
  src: string;
  /** A recipe name from effects.ts. An unknown or missing one gives a still picture. */
  effect?: string;
  /** Scales the strength of every layer (1 is normal, clamped to 0 to 3, a non-finite value gives 1). */
  intensity?: number;
  /** Name of a kit hue token (without the prefix, lowercase letters, digits and hyphens): the colour of the glow and the soft parts. Any other value falls back to blue. */
  hue?: string;
  /** Name of a kit hue token for the bright parts. Defaults to hue. */
  hot?: string;
  /** Positions on the picture the recipes read. */
  anchors?: ArtAnchors;
  /** A pixel size (fixed box, clamped to 1 to 1024, a non-finite value gives 28) or "fill" (takes the box that holds it, effects sized as for 84 px). */
  size?: number | 'fill';
  className?: string;
  /** When set the mark is an image with this label, otherwise it is hidden from assistive technology. */
  title?: string;
}

const BOLT_A = 'M5 6 L2 13 L6 18 L1.5 25 L5 33';
const BOLT_B = 'M35 5 L38.5 12 L34 18 L39 25 L35.5 34';

export function ArtMark({ src, effect, intensity = 1, hue = DEFAULT_HUE, hot, anchors = {}, size = 28, className, title }: ArtMarkProps) {
  const fill = size === 'fill';
  const px = fill ? 84 : isNum(size) ? Math.min(MAX_SIZE, Math.max(MIN_SIZE, size)) : 28;
  const gain = isNum(intensity) ? Math.min(MAX_INTENSITY, Math.max(0, intensity)) : 1;
  const fx = isArtHue(hue) ? hue : DEFAULT_HUE;
  const fxHot = isArtHue(hot) ? hot : fx;
  const masked = isArtSrcSafe(src);
  const name = artEffectFor(effect);
  const ref = useRef<HTMLSpanElement | null>(null);
  const paused = useArtPaused(ref);
  const layers: Readonly<Record<string, number>> = name ? ART_EFFECTS[name].layers : {};
  const style = {
    ...(fill ? {} : { width: px, height: px }),
    '--am-size': px,
    '--am-intensity': gain,
    '--am-fx': `var(--hue-${fx})`,
    '--am-fx-hot': `var(--hue-${fxHot})`,
    ...(masked ? { '--am-art': `url("${src}")` } : {}),
    ...artAnchorVars(anchors),
  } as CSSProperties;
  return (
    <span
      ref={ref}
      className={['art-mark', fill ? 'art-mark-fill' : '', className].filter(Boolean).join(' ')}
      data-effect={name}
      data-paused={paused ? '' : undefined}
      data-nomask={masked ? undefined : ''}
      style={style}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <span className="am-glow" />
      <img className="am-img" src={src} width={fill ? undefined : px} height={fill ? undefined : px} alt="" draggable={false} decoding="async" />
      <span className="am-fx">
        {Object.entries(layers).flatMap(([layer, count]) =>
          Array.from({ length: count }, (_, i) => (
            <span
              key={`${layer}${i}`}
              className={`am-${layer}`}
              data-n={i}
              style={(layer === 'arc' ? { '--i': i, '--r': `var(--am-r${i})` } : { '--i': i }) as unknown as CSSProperties}
            >
              {layer === 'feed' && <span className="am-feed-art" />}
              {layer === 'bolt' && (
                <svg viewBox="0 0 40 40" focusable="false" aria-hidden="true">
                  <path className="am-bolt-a" d={BOLT_A} />
                  <path className="am-bolt-b" d={BOLT_B} />
                </svg>
              )}
            </span>
          )),
        )}
      </span>
    </span>
  );
}
