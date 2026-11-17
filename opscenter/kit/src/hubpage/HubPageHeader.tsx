/* HubPageHeader: the one header of every hub page. The accent icon chip (the rail icon), the title
   EXACTLY as the rail names the hub (the caller reads it from the same navigation list, never types it
   on a page), a one line subtitle, a right slot for page meta, then the level one tabs, then the level
   two switch. Only an optional HubTabIntro may sit between it and the content. */

import type { ReactNode } from 'react';

export interface HubPageHeaderProps {
  /** The accent key of the hub, matched by the consumer's hub accent map. */
  hub: string;
  /** The rail icon. */
  icon: ReactNode;
  /** The rail label. */
  title: string;
  /** One plain line saying what the hub is for. No dots as separators. */
  subtitle: string;
  /** Page meta on the right: the updated time, a refresh, a primary action. */
  meta?: ReactNode;
  /** Level one: a HubTabs. */
  tabs?: ReactNode;
  /** Level two: a HubSegmented for the open tab's items. */
  switcher?: ReactNode;
  /** A HubTabIntro or any muted line that belongs to the open tab. */
  children?: ReactNode;
}

export function HubPageHeader({ hub, icon, title, subtitle, meta, tabs, switcher, children }: HubPageHeaderProps) {
  return (
    <header className="hp-head" data-hub={hub}>
      <div className="hp-head-top">
        <span className="hp-head-chip" aria-hidden="true">
          {icon}
        </span>
        <div className="hp-head-text">
          <h1 className="hp-head-title">{title}</h1>
          <p className="hp-head-sub">{subtitle}</p>
        </div>
        {meta ? <div className="hp-head-meta">{meta}</div> : null}
      </div>
      {tabs}
      {switcher ? <div className="hp-head-l2">{switcher}</div> : null}
      {children}
    </header>
  );
}

/** One muted line for the open tab, the place for a note such as "Updates write straight to the tracker". */
export function HubTabIntro({ children }: { children: ReactNode }) {
  return <p className="hp-tab-intro">{children}</p>;
}
