/* The kit's own chrome icons (close, chevron, search, check, sun, moon, pin and a few more the shell
   needs). Apps pass their own icons into components as ReactNode props. Every icon is an inline
   SVG drawn in currentColor, decorative by default (aria-hidden). */

import type { ReactElement, ReactNode, SVGProps } from 'react';

export type IconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & {
  size?: number | undefined;
};

export type IconComponent = (props: IconProps) => ReactElement;

function makeIcon(name: string, body: ReactNode): IconComponent {
  const Icon = ({ size = 16, ...rest }: IconProps): ReactElement => (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      data-icon={name}
      {...rest}
    >
      {body}
    </svg>
  );
  return Icon;
}

export const IconClose = makeIcon('close', <path d="M18 6 6 18M6 6l12 12" />);
export const IconChevronDown = makeIcon('chevron-down', <path d="m6 9 6 6 6-6" />);
export const IconChevronRight = makeIcon('chevron-right', <path d="m9 18 6-6-6-6" />);
export const IconChevronLeft = makeIcon('chevron-left', <path d="m15 18-6-6 6-6" />);
export const IconSearch = makeIcon(
  'search',
  <>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.6-3.6" />
  </>,
);
export const IconCheck = makeIcon('check', <path d="M20 6 9 17l-5-5" />);
export const IconSun = makeIcon(
  'sun',
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4" />
  </>,
);
export const IconMoon = makeIcon('moon', <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z" />);
/** A screen on a stand: the theme follows the operating system. */
export const IconMonitor = makeIcon(
  'monitor',
  <>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </>,
);
export const IconPin = makeIcon(
  'pin',
  <>
    <path d="M12 17v5" />
    <path d="M9 10.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.8a2 2 0 0 0-1.1-1.8l-1.8-.9a2 2 0 0 1-1.1-1.8V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1Z" />
  </>,
);
export const IconPinOff = makeIcon(
  'pin-off',
  <>
    <path d="M12 17v5" />
    <path d="M15 9.3V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.9" />
    <path d="M9 9v1.8a2 2 0 0 1-1.1 1.8l-1.8.9A2 2 0 0 0 5 15.2V16a1 1 0 0 0 1 1h11" />
    <path d="m2 2 20 20" />
  </>,
);
export const IconMenu = makeIcon('menu', <path d="M4 6h16M4 12h16M4 18h16" />);
export const IconRefresh = makeIcon(
  'refresh',
  <>
    <path d="M21 12a9 9 0 1 1-2.6-6.4L21 8" />
    <path d="M21 3v5h-5" />
  </>,
);
export const IconHome = makeIcon(
  'home',
  <>
    <path d="m3 10.5 9-7.5 9 7.5" />
    <path d="M5 9.5V21h5v-6h4v6h5V9.5" />
  </>,
);
export const IconInfo = makeIcon(
  'info',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 16v-4M12 8h.01" />
  </>,
);
export const IconHelp = makeIcon(
  'help',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 2.5-3 4M12 17h.01" />
  </>,
);
export const IconWarning = makeIcon(
  'warning',
  <>
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </>,
);
export const IconAlert = makeIcon(
  'alert',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 8v4M12 16h.01" />
  </>,
);
export const IconCheckCircle = makeIcon(
  'check-circle',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="m8.5 12 2.5 2.5 4.5-5" />
  </>,
);
export const IconSparkle = makeIcon(
  'sparkle',
  <path d="M12 3.5 13.8 9l5.7 1.8-5.7 1.9L12 18.5l-1.8-5.8-5.7-1.9L10.2 9Z" />,
);
export const IconPause = makeIcon('pause', <path d="M9 5v14M15 5v14" />);
export const IconPlay = makeIcon('play', <path d="M7 4.5v15L19 12Z" />);
export const IconClock = makeIcon(
  'clock',
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </>,
);
export const IconEye = makeIcon(
  'eye',
  <>
    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z" />
    <circle cx="12" cy="12" r="3" />
  </>,
);
export const IconEyeOff = makeIcon(
  'eye-off',
  <>
    <path d="M9.9 5.2A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-2.6 3.5M6.6 6.6A16.5 16.5 0 0 0 2 12s3.6 7 10 7a9.7 9.7 0 0 0 4.4-1.1" />
    <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18" />
  </>,
);
export const IconFolder = makeIcon('folder', <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />);
export const IconMail = makeIcon(
  'mail',
  <>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m3 7 9 6 9-6" />
  </>,
);
export const IconCalendar = makeIcon(
  'calendar',
  <>
    <rect x="3" y="4" width="18" height="17" rx="2" />
    <path d="M16 2v4M8 2v4M3 10h18" />
  </>,
);
export const IconTrash = makeIcon(
  'trash',
  <>
    <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M6 6l1 14a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-14" />
    <path d="M10 11v6M14 11v6" />
  </>,
);
export const IconEdit = makeIcon(
  'edit',
  <>
    <path d="M12 20h9" />
    <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
  </>,
);
export const IconList = makeIcon('list', <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />);
export const IconMore = makeIcon(
  'more',
  <>
    <circle cx="5" cy="12" r="1" />
    <circle cx="12" cy="12" r="1" />
    <circle cx="19" cy="12" r="1" />
  </>,
);
export const IconPlus = makeIcon('plus', <path d="M12 5v14M5 12h14" />);
export const IconArrowUp = makeIcon('arrow-up', <path d="M12 19V5M5 12l7-7 7 7" />);
export const IconShield = makeIcon('shield', <path d="M12 3 5 6v5.5c0 4.2 2.9 7.6 7 9 4.1-1.4 7-4.8 7-9V6Z" />);
export const IconCopy = makeIcon(
  'copy',
  <>
    <rect x="8" y="8" width="12" height="12" rx="2" />
    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
  </>,
);
export const IconGrid = makeIcon(
  'grid',
  <>
    <rect x="3" y="3" width="7" height="7" rx="1" />
    <rect x="14" y="3" width="7" height="7" rx="1" />
    <rect x="3" y="14" width="7" height="7" rx="1" />
    <rect x="14" y="14" width="7" height="7" rx="1" />
  </>,
);
export const IconExternal = makeIcon(
  'external',
  <>
    <path d="M15 3h6v6" />
    <path d="M10 14 21 3" />
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
  </>,
);
export const IconLogOut = makeIcon(
  'log-out',
  <>
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <path d="m16 17 5-5-5-5" />
    <path d="M21 12H9" />
  </>,
);
export const IconArrowLeft = makeIcon('arrow-left', <path d="M19 12H5M12 19l-7-7 7-7" />);
