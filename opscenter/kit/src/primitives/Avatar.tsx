/* Avatar: initials on a stable categorical hue per name (UI standard section 7). The hue never
   matches the one the app accent withholds from data. */

import type { ReactNode } from 'react';
import { useCategoricalHues } from '../charts/chartTheme';
import { cx } from '../lib/env';
import { hueFor, initialsOf } from '../lib/hues';
import type { MarkHue } from '../lib/hues';

export interface AvatarProps {
  name: string;
  /** Photo URL. Initials show when omitted. */
  src?: string | undefined;
  /** An icon instead of initials, for groups. */
  icon?: ReactNode;
  /** Fixed hue. Default: a stable hue from the name, never the withheld accent hue. */
  hue?: MarkHue | undefined;
  size?: 'sm' | 'md' | 'lg' | undefined;
  className?: string | undefined;
}

export function Avatar({ name, src, icon, hue, size = 'md', className }: AvatarProps) {
  const hues = useCategoricalHues();
  const h = hue ?? hueFor(name, hues);
  return (
    <span className={cx('avatar', `hue-${h}`, className)} data-size={size} role="img" aria-label={name}>
      {src ? <img src={src} alt="" /> : icon ? <span aria-hidden="true">{icon}</span> : <span aria-hidden="true">{initialsOf(name)}</span>}
    </span>
  );
}
