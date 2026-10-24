/* The kit gallery: every component on one page, with a theme switch and an accent switcher. Each
   specimen section has a stable id (specimen-*) for the visual regression screenshots. The same
   component is rendered by the a11y test, so the gallery is also the axe composite. */

import { lazy, Suspense, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  APP_ACCENTS,
  ART_EFFECTS,
  ArtMark,
  AccentProvider,
  AccountMenu,
  AnnouncementStack,
  AppShell,
  Avatar,
  Badge,
  BuildCard,
  Button,
  CATEGORICAL_HUES,
  Card,
  Checkbox,
  Combobox,
  UnavailableError,
  EXTRA_HUES,
  CardBody,
  CardHead,
  CommandPalette,
  EmptyState,
  FeedStrip,
  Field,
  Header,
  usePagedState,
  paginate,
  applySort,
  applyGrouping,
  PersonOption,
  ListControls,
  GroupHeader,
  HueTile,
  ButtonLink,
  IconButton,
  IconCheck,
  IconInfo,
  IconMenu,
  IconMore,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSparkle,
  IconWarning,
  Input,
  Kbd,
  Menu,
  Modal,
  ModalSection,
  NavGroup,
  NavItem,
  PageHeader,
  Pill,
  Popover,
  Radio,
  RadioGroup,
  Rail,
  SearchTrigger,
  Segmented,
  ChipGroup,
  Spinner,
  Select,
  Stat,
  StatRow,
  Markdown,
  Disclosure,
  FactList,
  FactRow,
  Switch,
  ShortcutLayer,
  Skeleton,
  MonthGrid,
  StatTile,
  FreshnessGrid,
  StatusDot,
  StickFigure,
  Table,
  TabPanel,
  Tabs,
  Textarea,
  ThemeProvider,
  ThemeToggle,
  Toaster,
  Tone,
  Toolbar,
  TooltipLayer,
  openCommandPalette,
  openScopedPalette,
  useCategoricalHues,
  useChartTheme,
  useConfirm,
  usePrompt,
  useShortcut,
  useTheme,
  useToast,
  Breadcrumb,
  CopyButton,
  Forbidden,
  ImpersonationBanner,
  Mono,
  Pagination,
  ProgressBar,
  SearchInput,
  TextDiff,
  ErrorState,
  FormSection,
  ListFooter,
  ListTable,
  SelectionBar,
  FilterPanel,
  useBulkRun,
  SplitLayout,
  useRowSelection,
  usePagination,
  ActionsBlock,
  FeedBlock,
  HubHome,
  IconPinOff,
  IconCalendar,
  IconClock,
  IconEdit,
  IconEye,
  IconEyeOff,
  IconFolder,
  IconList,
  IconMail,
  IconTrash,
  PinButton,
  PinnedBlock,
  ToolLauncher,
  ToolSwitchButton,
  createMemoryPinsStore,
  createMemoryTileOrderStore,
  paletteScope,
  TileReorderStatus,
  useTileReorder,
  useToolLauncher,
  PageErrorBoundary,
  RecordChip,
  RecordPreviewProvider,
  createRecordRegistry,
} from '../src/index';
import type { AppAccent, ArtAnchors, BulkRunState, ComboboxFreeEntry, FilterClause, FilterField, HomeTool, LauncherTool, PaletteItem, Recent, ReleaseNote, SortDirection, SortState, TableColumn, ThemeChoice } from '../src/index';
import { AreaChart, BarChart, ChartLegend, DonutChart, Gauge, LineChart, RingProgress, Sparkline } from '../src/charts';
import { Graph, graphEdge } from '../src/graph';
import type { Edge, GraphCardNode } from '../src/graph';

/* Scalar is a large app: the API reference specimen loads it only when a reader opens it. */
const ApiReferenceDemo = lazy(() => import('./ApiReferenceDemo'));

export const SAMPLE_RELEASES: ReleaseNote[] = [
  {
    version: '0.1.0',
    date: '2026-10-12',
    title: '3 new, 1 fixed',
    items: [
      { type: 'new', title: 'Shared React kit with the shell, primitives and overlays' },
      { type: 'new', title: 'Command palette on Cmd or Ctrl and K' },
      { type: 'new', title: 'Build card with generated release notes' },
      { type: 'fixed', title: 'Escape closes the palette from a focused row' },
    ],
  },
];

interface Row {
  id: string;
  name: string;
  owner: string;
  status: 'Healthy' | 'Degraded' | 'Offline';
  devices: number;
  updated: string;
}

const ROWS: Row[] = [
  { id: 'r1', name: 'Build agents', owner: 'Platform', status: 'Healthy', devices: 42, updated: '2026-10-11' },
  { id: 'r2', name: 'Print queue', owner: 'Workplace', status: 'Degraded', devices: 7, updated: '2026-10-09' },
  { id: 'r3', name: 'Kiosk fleet', owner: 'Facilities', status: 'Offline', devices: 118, updated: '2026-10-12' },
  { id: 'r4', name: 'Lab devices', owner: 'Research', status: 'Healthy', devices: 9, updated: '' },
];

const STICK_POSES = ['idle', 'wave', 'shrug', 'megaphone', 'alert', 'clipboard'] as const;

const STATUS_TONE = { Healthy: 'success', Degraded: 'warning', Offline: 'danger' } as const;

const COLUMNS: TableColumn<Row>[] = [
  { key: 'name', header: 'Name' },
  { key: 'owner', header: 'Owner' },
  {
    key: 'status',
    header: 'Status',
    render: (r) =>
      r.status === 'Degraded' ? (
        <Pill tone="warning" live>
          Recovering
        </Pill>
      ) : (
        <Badge tone={STATUS_TONE[r.status]} dot>
          {r.status}
        </Badge>
      ),
  },
  { key: 'devices', header: 'Devices', numeric: true },
  { key: 'updated', header: 'Updated', render: (r) => r.updated || 'Never' },
];

function Specimen({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={`specimen-${id}`} data-specimen={id} className="gallery-section" aria-labelledby={`specimen-${id}-title`}>
      <h2 id={`specimen-${id}-title`} className="gallery-section-title">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ThemeControls({ accent, onAccent }: { accent: AppAccent; onAccent: (a: AppAccent) => void }) {
  const { choice, setChoice } = useTheme();
  return (
    <div className="gallery-row">
      <Segmented<ThemeChoice>
        label="Theme"
        value={choice}
        onChange={(v) => setChoice(v)}
        options={[
          { value: 'system', label: 'System' },
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
        ]}
      />
      <div className="gallery-accent">
        <Field label="Accent" hint="Set once on the root as data-app-accent. Cobalt is the default and sets no attribute.">
          <Select value={accent} onChange={(e) => onAccent(e.target.value as AppAccent)} options={APP_ACCENTS.map((a) => ({ value: a, label: a }))} />
        </Field>
      </div>
    </div>
  );
}

function SearchRoutingSpecimen() {
  const [routed, setRouted] = useState(0);
  return (
    <div className="gallery-row">
      <span className="gallery-note">SearchTrigger onSearch: routes to the app's own search instead of the kit palette.</span>
      <SearchTrigger label="Search the app" onSearch={() => setRouted((n) => n + 1)} />
      <span className="gallery-note" aria-live="polite">{routed ? `Routed to the app's search ${routed} time(s)` : 'Not routed yet'}</span>
    </div>
  );
}

function ButtonsSpecimen() {
  const [loading, setLoading] = useState(false);
  return (
    <div className="gallery-row">
      <Button variant="primary" icon={<IconPlus />}>
        Add device
      </Button>
      <Button variant="secondary">Export</Button>
      <ButtonLink variant="secondary" href="#specimen-table">
        Go to table
      </ButtonLink>
      <Button variant="ghost">Cancel</Button>
      <Button variant="danger">Delete</Button>
      <Button variant="primary" loading={loading} onClick={() => setLoading(true)}>
        Save
      </Button>
      <Button variant="secondary" size="sm">
        Small
      </Button>
      <IconButton label="Refresh" icon={<IconRefresh />} variant="secondary" />
      <IconButton label="More actions" icon={<IconMore />} kbd="M" />
      <Button variant="secondary" disabled>
        Disabled
      </Button>
      <span className="gallery-break" aria-hidden="true" />
      <Button variant="success" icon={<IconCheck />}>
        Approve
      </Button>
      <Button variant="success-subtle">Mark resolved</Button>
      <Button variant="warning" icon={<IconWarning />}>
        Pause queue
      </Button>
      <Button variant="warning-subtle">Snooze</Button>
      <Button variant="danger-subtle">Remove</Button>
      <Button variant="success" size="sm">
        Small solid
      </Button>
      <Button variant="warning-subtle" size="sm">
        Small subtle
      </Button>
    </div>
  );
}

function MarksSpecimen() {
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <Badge>Neutral</Badge>
        <Badge tone="accent">Accent</Badge>
        <Badge tone="success" dot>
          Healthy
        </Badge>
        <Badge tone="warning" dot>
          Degraded
        </Badge>
        <Badge tone="urgent" dot>
          High priority
        </Badge>
        <Badge tone="danger" dot>
          Offline
        </Badge>
        <Badge tone="info">Info</Badge>
        <Pill hue="violet">Design</Pill>
        <Pill hue="teal">Platform</Pill>
      </div>
      <div className="gallery-row">
        <StatusDot tone="success" label="Live" showLabel />
        <StatusDot tone="warning" label="Degraded" showLabel />
        <StatusDot tone="urgent" label="Escalated" showLabel />
        <StatusDot tone="danger" label="Down" showLabel />
        <StatusDot tone="neutral" label="Unknown" showLabel />
        <span>
          Press <Kbd>?</Kbd> for shortcuts
        </span>
      </div>
      <div className="gallery-row">
        {CATEGORICAL_HUES.map((h) => (
          <HueTile key={h} hue={h} label={`${h} tile`}>
            <IconSparkle />
          </HueTile>
        ))}
        {EXTRA_HUES.map((h) => (
          <HueTile key={h} hue={h} label={`${h} tile, extra hue`}>
            <IconSparkle />
          </HueTile>
        ))}
        <Pill hue="yellow">Yellow toner</Pill>
        <Pill hue="ink">Black toner</Pill>
      </div>
      <div className="gallery-row">
        <Avatar name="Avery Stone" />
        <Avatar name="Jordan Lee" size="lg" />
        <Avatar name="Sam Rivera" size="sm" />
        <Avatar name="Ops group" icon={<IconInfo />} hue="teal" />
      </div>
      <div className="gallery-grid">
        <Tone hue="amber">Tone wraps content in a corner wash and a tinted hairline all the way round.</Tone>
        <Card selected>
          <CardHead title="Selected card" subtitle="Raised neutral surface with a full hairline ring" level={3} />
        </Card>
      </div>
    </div>
  );
}

function WorkingSpecimen() {
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <Spinner size="xs" />
        <Spinner />
        <Spinner size="md" />
        <Spinner size="lg" label="Loading the queue" />
        <span className="gallery-note">Decorative by default. A label makes it a status. Reduced motion holds the arc still.</span>
      </div>
      <div className="gallery-row">
        <Pill tone="info" live>
          Syncing
        </Pill>
        <Pill tone="accent" live>
          Deploying
        </Pill>
        <Pill tone="warning" live>
          Retrying
        </Pill>
        <Pill tone="urgent" live>
          Escalating
        </Pill>
        <Pill tone="success" live>
          Finishing
        </Pill>
        <Pill live>Queued</Pill>
      </div>
    </div>
  );
}

function MonthGridSpecimen() {
  const [picked, setPicked] = useState<string | undefined>('2026-10-14');
  const events = [
    { id: '1', date: '2026-10-05', label: 'Primary shift', tone: 'accent' as const },
    { id: '2', date: '2026-10-14', label: 'Out of office', tone: 'warning' as const },
    { id: '3', date: '2026-10-14', label: 'Backup shift' },
    { id: '4', date: '2026-10-14', label: 'Review', tone: 'info' as const },
    { id: '5', date: '2026-10-14', label: 'Handover', tone: 'success' as const },
    { id: '6', date: '2026-10-23', label: 'Release window', tone: 'danger' as const },
  ];
  return <MonthGrid year={2026} month={9} label="Example calendar" today="2026-10-23" events={events} selected={picked} onSelectDay={setPicked} />;
}

function StatSpecimen() {
  return (
    <div className="stat-grid">
      <StatTile label="Managed devices" value={4218} hint="Up 3% this week" icon={<IconCheck />} />
      <StatTile label="Compliance" value="98.5%" tone="success" hint="Target 97%" />
      <StatTile label="Pending updates" value={37} tone="warning" />
      <StatTile label="Open tickets" value={128} tone="info" delta={{ text: "12 fewer than last week", direction: "down" }} selected tip="Open tickets in the queue" onClick={() => undefined} />
      <StatTile label="Enrolled" value={4218} tone="success" delta={{ text: "3% this week", direction: "up" }} />
      <StatTile label="Failed jobs" value={2} tone="danger" onClick={() => undefined} hint="Open the job list" />
      <StatTile label="Spend" value="$12,480" hue="violet" />
    </div>
  );
}

function FactsSpecimen() {
  return (
    <div className="gallery-stack">
      <div style={{ maxWidth: 360 }}>
        <FactList label="Device facts">
          <FactRow label="Name" value="Front desk 4" tone="primary" />
          <FactRow label="Serial" value="C02X81ABCD12" mono />
          <FactRow label="Owner" value={null} />
          <FactRow label="Disk" value="Almost full" tone="warning" />
          <FactRow label="Backup" value="Failed" tone="danger" />
          <FactRow label="Encryption" value="On" tone="success" />
          <FactRow label="Path" value="/Library/Application Support/Example/very/long/path/that/must/wrap/cleanly.log" mono hint="Full path on disk" />
        </FactList>
      </div>
      <div style={{ maxWidth: 360 }}>
        <Disclosure label="More detail" count={2}>
          <FactList>
            <FactRow label="Enrolled" value="2026-09-02" />
            <FactRow label="Last check-in" value="12 minutes ago" />
          </FactList>
        </Disclosure>
        <Disclosure label="Loads on open" lazy count="lazy" style={{ ['--disclosure-gap' as string]: '12px' }}>
          <FactList style={{ ['--fact-gap' as string]: '14px' }}>
            <FactRow label="Mounted" value="Only while open" />
            <FactRow label="Gap" value="Set by the caller" />
          </FactList>
        </Disclosure>
        <Disclosure label="Open by default" defaultOpen dense>
          <FactRow label="Channel" value="Stable" />
        </Disclosure>
      </div>
    </div>
  );
}

const MARKDOWN_SAMPLE = [
  '# Plan title',
  'A paragraph with **bold**, *italic*, `code` and a [safe link](https://example.com/page).',
  '## Checklist',
  '- [x] Done item',
  '- [ ] Open item',
  '  - Nested item',
  '1. First',
  '2. Second',
  '> A quoted note.',
  '| Name | State |',
  '| --- | --- |',
  '| Alpha | Ready |',
  '| Beta | Waiting |',
  '```',
  'const a = 1;',
  '```',
  '---',
  'A [script link](javascript:alert(1)) shows as text, and <b>raw html</b> shows as text too.',
].join('\n');

function MarkdownSpecimen() {
  const [opened, setOpened] = useState('');
  return (
    <div className="gallery-stack" style={{ maxWidth: 640 }}>
      <Markdown body={MARKDOWN_SAMPLE + '\n\nOpen the [next document](docs/next.md) in place.'} onLink={setOpened} />
      {opened ? (
        <p className="gallery-note" role="status">
          Asked to open {opened}
        </p>
      ) : null}
    </div>
  );
}

function StatsSpecimen() {
  const [filter, setFilter] = useState('all');
  return (
    <div className="gallery-stack">
      <StatRow label="Fleet summary">
        <Stat label="Devices" value={4218} hint="Across 12 sites" icon={<IconCheck />} hue="teal" onClick={() => setFilter('all')} selected={filter === 'all'} />
        <Stat label="Offline" value={14} tone="danger" hint="Over 24 hours" icon={<IconWarning />} hue="red" onClick={() => setFilter('offline')} selected={filter === 'offline'} />
        <Stat label="Pending updates" value={37} tone="warning" icon={<IconRefresh />} hue="amber" />
        <Stat label="Compliance" value="98.5%" tone="success" hint="Target 97%" />
        <Stat label="Black toner" value="8%" icon={<IconInfo />} hue="ink" hint="Reorder below 10%" />
      </StatRow>
      <p className="gallery-note">Stat is the light card for everyday summaries. StatTile above stays the deep hero tile.</p>
    </div>
  );
}

function ChoicesSpecimen() {
  const [ring, setRing] = useState('pilot');
  const [auto, setAuto] = useState(true);
  return (
    <div className="gallery-grid">
      <div className="gallery-stack">
        <Checkbox label="Email me a daily digest" description="Sent at 8am in your time zone." defaultChecked />
        <Checkbox label="Include archived devices" />
        <Checkbox label="Select all rows" indeterminate />
        <Checkbox label="Locked by policy" disabled defaultChecked />
        <Checkbox label="Compact checkbox" size="sm" defaultChecked />
      </div>
      <RadioGroup
        label="Update ring"
        value={ring}
        onChange={setRing}
        hint="Pilot gets updates a week early."
        options={[
          { value: 'pilot', label: 'Pilot', description: 'About 5 percent of devices' },
          { value: 'broad', label: 'Broad' },
          { value: 'frozen', label: 'Frozen', disabled: true },
        ]}
      />
      <div className="gallery-stack">
        <RadioGroup label="Density" defaultValue="comfortable" orientation="horizontal" size="sm">
          <Radio value="comfortable" label="Comfortable" />
          <Radio value="compact" label="Compact" />
        </RadioGroup>
        <Switch label="Auto refresh" description="Every 30 seconds while the tab is visible." checked={auto} onChange={setAuto} />
        <Switch label="Maintenance mode" />
        <Switch label="Small switch" size="sm" defaultChecked />
        <Switch label="Locked switch" disabled />
      </div>
    </div>
  );
}

function TabsSpecimen() {
  const [tab, setTab] = useState('overview');
  const [pill, setPill] = useState('day');
  const [range, setRange] = useState<'1h' | '24h' | '7d'>('24h');
  const [queue, setQueue] = useState<'all' | 'late' | 'failed' | 'done'>('all');
  const [layout, setLayout] = useState<'list' | 'search' | 'info'>('list');
  const [severity, setSeverity] = useState<('critical' | 'high' | 'medium' | 'low')[]>(['critical', 'high']);
  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'devices', label: 'Devices', badge: 12 },
    { id: 'policies', label: 'Policies' },
    { id: 'reports', label: 'Reports' },
    { id: 'archive', label: 'Archive', disabled: true },
  ];
  return (
    <div className="gallery-stack">
      <Tabs label="Sections" items={tabs} value={tab} onChange={setTab} idBase="gallery-tabs" withPanels />
      {tabs.map((t) =>
        t.id === tab ? (
          <TabPanel key={t.id} idBase="gallery-tabs" tabId={t.id}>
            <p className="gallery-note">The {t.label.toLowerCase()} panel.</p>
          </TabPanel>
        ) : null,
      )}
      <Tabs
        label="Period"
        variant="pills"
        items={[
          { id: 'day', label: 'Day' },
          { id: 'week', label: 'Week' },
          { id: 'month', label: 'Month' },
        ]}
        value={pill}
        onChange={setPill}
      />
      <Segmented
        label="Range"
        value={range}
        onChange={setRange}
        options={[
          { value: '1h', label: '1h' },
          { value: '24h', label: '24h' },
          { value: '7d', label: '7d' },
        ]}
      />
      <Segmented
        label="Queue"
        value={queue}
        onChange={setQueue}
        options={[
          { value: 'all', label: 'All', badge: 42 },
          { value: 'late', label: 'Late', tone: 'warning', badge: 6 },
          { value: 'failed', label: 'Failed', tone: 'danger', badge: 2 },
          { value: 'done', label: 'Done', tone: 'success' },
        ]}
      />
      <Segmented
        label="Layout"
        value={layout}
        onChange={setLayout}
        options={[
          { value: 'list', label: 'List', icon: <IconMenu /> },
          { value: 'search', label: 'Search', icon: <IconSearch /> },
          { value: 'info', label: 'Details', icon: <IconInfo />, iconOnly: true },
        ]}
      />
      <ChipGroup
        label="Severity filter"
        value={severity}
        onChange={setSeverity}
        options={[
          { value: 'critical', label: 'Critical', tone: 'danger' },
          { value: 'high', label: 'High', tone: 'urgent', badge: 8 },
          { value: 'medium', label: 'Medium', tone: 'warning' },
          { value: 'low', label: 'Low', tone: 'info', disabled: true },
        ]}
      />
    </div>
  );
}

function FieldsSpecimen() {
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [view, setView] = useState<'list' | 'grid'>('list');
  return (
    <div className="gallery-grid">
      <Field label="Device name" hint="Shown in reports and alerts." required>
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="For example Lab kiosk 4" />
      </Field>
      <Field label="Serial number" error="Enter a serial number in the format AB-1234.">
        <Input defaultValue="1234" />
      </Field>
      <Field label="Ring" optional>
        <Select
          defaultValue="pilot"
          options={[
            { value: 'pilot', label: 'Pilot' },
            { value: 'broad', label: 'Broad' },
          ]}
        />
      </Field>
      <div className="gallery-stack">
        <p id="gallery-owner-label" className="gallery-note">
          Owner (a select labelled by this line)
        </p>
        <Select
          labelledBy="gallery-owner-label"
          defaultValue="any"
          options={[
            { value: 'any', label: 'Any owner' },
            { value: 'me', label: 'Me' },
          ]}
        />
      </div>
      <Field label="Notes" counter={{ value: notes.length, max: 200 }}>
        <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={200} />
      </Field>
      <div className="gallery-stack">
        <p className="gallery-note">Input size sm matches the Segmented height in a toolbar.</p>
        <div className="gallery-row">
          <Input size="sm" placeholder="Filter" aria-label="Compact filter" className="gallery-compact-input" />
          <Segmented
            label="Compact view"
            value={view}
            onChange={setView}
            options={[
              { value: 'list', label: 'List' },
              { value: 'grid', label: 'Grid' },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function TableSpecimen() {
  const [filter, setFilter] = useState('');
  const [selected, setSelected] = useState<string | null>('r2');
  const [sort, setSort] = useState<SortState | null>({ key: 'name', dir: 'asc' });
  return (
    <Card>
      <CardHead title="Device groups" subtitle="Every column sorts. Arrow keys move between rows." level={3} />
      <Toolbar onRefresh={() => undefined} updatedAt={Date.now()} actions={<Button variant="secondary" size="sm">Export</Button>}>
        <Field label="Filter">
          <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter rows" />
        </Field>
      </Toolbar>
      <Table
        caption="Device groups"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        filter={filter}
        onRowActivate={(r) => setSelected(r.id)}
        isRowSelected={(r) => r.id === selected}
        sort={sort}
        onSortChange={setSort}
        rowProps={(r) => ({ 'data-status': r.status })}
      />
      <CardHead title="Compact density" subtitle="Tighter rows for a long list; a touch screen keeps the comfortable rows" level={3} />
      <Table caption="Device groups, compact" density="compact" columns={COLUMNS} rows={ROWS} rowKey={(r) => r.id} />
    </Card>
  );
}

function EmptySpecimen() {
  return (
    <div className="gallery-grid">
      <Card>
        <EmptyState title="No devices yet" body="Enrolled devices show up here." icon={<IconSearch />} hue="blue" action={<Button variant="primary">Enrol a device</Button>} />
      </Card>
      <Card>
        <EmptyState title="All clear" body="Nothing needs attention." pose="celebrate" />
      </Card>
      <Card>
        <Skeleton variant="lines" count={3} />
        <Skeleton variant="card" />
        <Skeleton variant="table" count={2} columns={3} label="Loading table" />
      </Card>
      <Card>
        <CardHead title="Stick figure" subtitle="Every pose, on an even grid" level={3} />
        <CardBody>
          <ul className="gallery-poses" aria-label="Stick figure poses">
            {STICK_POSES.map((p) => (
              <li key={p} className="gallery-pose">
                <StickFigure pose={p} />
                <span className="gallery-note">{p}</span>
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </div>
  );
}

function WayfindingSpecimen() {
  const [q, setQ] = useState('edge');
  return (
    <div className="gallery-grid">
      <Card>
        <CardHead title="Breadcrumb and pagination" level={3} />
        <CardBody className="gallery-stack">
          <Breadcrumb items={[{ label: 'Fleet', href: '#' }, { label: 'Sites', href: '#' }, { label: 'North hall' }]} />
          <Pagination page={2} pageSize={40} total={312} unit="devices" onPrev={() => undefined} onNext={() => undefined} />
          <Pagination page={3} pageSize={25} itemCount={25} hasMore onPage={() => undefined} />
          <Pagination page={4} pageSize={25} itemCount={11} onPage={() => undefined} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Search, text and progress" level={3} />
        <CardBody className="gallery-stack">
          <SearchInput value={q} onChange={setQ} placeholder="Filter devices" />
          <p className="gallery-note">
            Serial <Mono>SN-0042-7731</Mono> <Mono dim>/</Mono> <CopyButton value="192.0.2.17" />
          </p>
          <ProgressBar value={64} label="Sync progress" />
          <ProgressBar value={92} tone="warning" label="Disk use" />
          <ProgressBar label="Project work" max={20} segments={[{ value: 9, tone: "success", label: "done" }, { value: 4, tone: "info", label: "in progress" }]} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Text diff" level={3} />
        <CardBody>
          <TextDiff before={'retries: 3\ntimeout: 30s\nmode: strict'} after={'retries: 5\ntimeout: 30s\nmode: strict\nlog: debug'} beforeLabel="Saved" afterLabel="Current" />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Text diff with line numbers" level={3} />
        <CardBody>
          <TextDiff
            lineNumbers
            before={'retries: 3\ntimeout: 30s\nmode: strict\nlevel: info'}
            after={'retries: 5\ntimeout: 30s\nmode: strict\nlog: debug\nlevel: info'}
            beforeLabel="Saved"
            afterLabel="Current"
          />
        </CardBody>
      </Card>
      <Card>
        <ImpersonationBanner roleName="Reader" asUser="ada" onExit={() => undefined} />
        <Forbidden permission="devices.write" homeHref="#" />
      </Card>
    </div>
  );
}

interface LookupPerson {
  id: string;
  name: string;
  team: string;
  title?: string;
}

const LOOKUP_PEOPLE: readonly LookupPerson[] = [
  { id: 'u1', name: 'Avery Stone', team: 'Platform team', title: 'Designer' },
  { id: 'u2', name: 'Avery Lin', team: 'Support team' },
  { id: 'u3', name: 'Jordan Lee', team: 'Field team', title: 'Lead' },
  { id: 'u4', name: 'Sam Rivera', team: 'Data team', title: 'Analyst' },
];

/** A stand-in for an app's directory: filters the list after a short wait and honours the abort signal. */
function searchPeople(query: string, signal: AbortSignal): Promise<readonly LookupPerson[]> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => resolve(LOOKUP_PEOPLE.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))), 350);
    signal.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('aborted', 'AbortError'));
    });
  });
}

function searchFailing(): Promise<readonly LookupPerson[]> {
  return Promise.reject(new Error('Lookup unavailable'));
}

/** A lookup that is not available at all: the part falls back to free entry. */
function searchUnavailable(): Promise<readonly LookupPerson[]> {
  return Promise.reject(new UnavailableError());
}

function checkCode(text: string): string | null {
  return /^[A-Z]{2}-\d{3}$/.test(text) ? null : 'Enter a code like AB-123.';
}

interface ListRow {
  id: string;
  name: string;
  site: string;
  size: number;
}

const LIST_ROWS: readonly ListRow[] = [
  { id: 'l1', name: 'Reception kiosk', site: 'North hall', size: 12 },
  { id: 'l2', name: 'Lab bench 4', site: 'South wing', size: 40 },
  { id: 'l3', name: 'Print queue', site: 'North hall', size: 7 },
  { id: 'l4', name: 'Loading dock', site: 'East yard', size: 21 },
  { id: 'l5', name: 'Lab bench 10', site: 'South wing', size: 3 },
];

const LIST_GETTERS = { name: (r: ListRow) => r.name, site: (r: ListRow) => r.site, size: (r: ListRow) => r.size };

function freeText(value: LookupPerson | ComboboxFreeEntry): string {
  return 'free' in value ? value.free : value.name;
}

function LookupAndListSpecimen() {
  const [chosen, setChosen] = useState<LookupPerson[]>([]);
  const [owner, setOwner] = useState('');
  const [freeAdded, setFreeAdded] = useState('');
  const [sortKey, setSortKey] = useState<string | null>('name');
  const [sortDir, setSortDir] = useState<SortDirection>('asc');
  const [groupKey, setGroupKey] = useState<string | null>('site');
  const [site, setSite] = useState('');
  const paged = usePagedState(3);
  const filtered = LIST_ROWS.filter((r) => !site || r.site === site);
  const sorted = applySort(filtered, sortKey, sortDir, LIST_GETTERS);
  const shown = paginate(sorted, paged.page, paged.pageSize);
  const groups = applyGrouping(shown, groupKey, LIST_GETTERS);
  const sites = [...new Set(LIST_ROWS.map((r) => r.site))].map((v) => ({ value: v, label: v }));
  const rowText = (r: ListRow) => (
    <li key={r.id} className="gallery-list-row">
      <span>{r.name}</span>
      <Mono dim>{r.size}</Mono>
    </li>
  );
  return (
    <div className="gallery-grid">
      <Card>
        <CardHead title="Person picker" subtitle="One Combobox over an async search, Avatar rows through the row slot." level={3} />
        <CardBody className="gallery-stack">
          <Field label="Add a person" hint="Type two letters. The lookup waits, cancels stale replies and keeps the keyboard on the input.">
            <Combobox<LookupPerson>
              placeholder="Search people"
              search={searchPeople}
              getKey={(p) => p.id}
              getLabel={(p) => p.name}
              excludeKeys={chosen.map((p) => p.id)}
              clearOnSelect
              onSelect={(p) => setChosen((list) => [...list, p])}
              renderOption={(p) => <PersonOption person={{ name: p.name, detail: p.team, meta: p.title }} />}
            />
          </Field>
          <div className="gallery-row">
            {chosen.length === 0 ? <span className="gallery-note">No one added yet.</span> : chosen.map((p) => <Badge key={p.id}>{p.name}</Badge>)}
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Same part, plain rows and a failing lookup" level={3} />
        <CardBody className="gallery-stack">
          <Field label="Owner">
            <Combobox<LookupPerson>
              placeholder="Search by name"
              search={searchPeople}
              getKey={(p) => p.id}
              getLabel={(p) => p.name}
              onSelect={(p) => setOwner(p.name)}
              messages={{ empty: (q) => `Nobody called "${q}"` }}
            />
          </Field>
          <p className="gallery-note" role="status">
            {owner ? `Owner set to ${owner}` : 'No owner set'}
          </p>
          <Field label="Directory (always failing)">
            <Combobox<LookupPerson> placeholder="Search, then retry" search={searchFailing} getKey={(p) => p.id} getLabel={(p) => p.name} onSelect={() => undefined} />
          </Field>
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Free entry when the lookup is unavailable" subtitle="The search rejects with an UnavailableError, so the input takes a validated free entry." level={3} />
        <CardBody className="gallery-stack">
          <Field label="Add by code (at rest)">
            <Combobox<LookupPerson, ComboboxFreeEntry>
              placeholder="Type a code"
              defaultUnavailable
              search={searchUnavailable}
              validate={checkCode}
              getKey={(p) => p.id}
              getLabel={(p) => p.name}
              onSelect={(v) => setFreeAdded(freeText(v))}
            />
          </Field>
          <Field label="Add by code (try it)">
            <Combobox<LookupPerson, ComboboxFreeEntry>
              placeholder="Type two letters, then a code"
              search={searchUnavailable}
              validate={checkCode}
              getKey={(p) => p.id}
              getLabel={(p) => p.name}
              onSelect={(v) => setFreeAdded(freeText(v))}
            />
          </Field>
          <p className="gallery-note" role="status">
            {freeAdded ? `Added ${freeAdded}` : 'Nothing added yet'}
          </p>
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Row slot at rest" subtitle="The person row as it draws, active row marked." level={3} />
        <CardBody>
          <ul className="combobox-list gallery-row-preview">
            {LOOKUP_PEOPLE.slice(0, 3).map((p, i) => (
              <li key={p.id} className="combobox-option" data-active={i === 0 ? 'true' : undefined}>
                <PersonOption person={{ name: p.name, detail: p.team, meta: p.title }} />
              </li>
            ))}
          </ul>
        </CardBody>
      </Card>
      <Card className="gallery-span">
        <CardHead title="List controls" subtitle="Filter, sort and group above the list, paging below." level={3} />
        <CardBody className="gallery-stack">
          <ListControls
            filters={[{ id: 'site', label: 'Site', allLabel: 'All sites', value: site, onChange: (v) => { setSite(v); paged.reset(); }, options: sites }]}
            sortOptions={[{ id: 'name', label: 'Name' }, { id: 'size', label: 'Size' }]}
            sortKey={sortKey}
            sortDir={sortDir}
            onSortKeyChange={setSortKey}
            onSortDirChange={setSortDir}
            groupOptions={[{ id: 'site', label: 'Site' }]}
            groupKey={groupKey}
            onGroupKeyChange={setGroupKey}
            rightSlot={<span className="gallery-note">{sorted.length} rows</span>}
          />
          <div>
            {groups
              ? groups.map((g) => (
                  <div key={g.key}>
                    <GroupHeader label={g.label} count={g.items.length} />
                    <ul className="gallery-list">{g.items.map(rowText)}</ul>
                  </div>
                ))
              : <ul className="gallery-list">{shown.map(rowText)}</ul>}
            <Pagination
              page={paged.page}
              pageSize={paged.pageSize}
              total={sorted.length}
              unit="rows"
              pageSizeOptions={[3, 5, 10]}
              onPageSizeChange={paged.setPageSize}
              onPrev={() => paged.setPage(paged.page - 1)}
              onNext={() => paged.setPage(paged.page + 1)}
            />
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function OverlaysSpecimen() {
  const [modal, setModal] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [bare, setBare] = useState(false);
  const [wide, setWide] = useState(false);
  const [pop, setPop] = useState(false);
  const popRef = useRef<HTMLButtonElement | null>(null);
  const confirmer = useConfirm();
  const prompter = usePrompt();
  const { toast } = useToast();
  const [result, setResult] = useState('Nothing yet');
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <Button variant="secondary" onClick={() => setModal(true)}>
          Open dialog
        </Button>
        <Button variant="secondary" onClick={() => setSheet(true)}>
          Open sheet
        </Button>
        <Button variant="secondary" onClick={() => setBare(true)}>
          Open headless dialog
        </Button>
        <Button variant="secondary" onClick={() => setWide(true)}>
          Open wide dialog
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            toast('info', 'Sync running', { id: 'gallery-sync', persistent: true });
            window.setTimeout(() => toast('success', 'Sync finished', { id: 'gallery-sync' }), 1500);
          }}
        >
          Toast updated in place
        </Button>
        <Button
          variant="danger"
          onClick={async () => {
            const ok = await confirmer.confirm({
              title: 'Delete this schedule?',
              body: 'Everyone on it stops getting reminders. This cannot be undone.',
              confirmLabel: 'Delete',
              danger: true,
            });
            setResult(ok ? 'Deleted' : 'Kept');
          }}
        >
          Delete schedule
        </Button>
        <Button
          variant="secondary"
          onClick={async () => {
            const value = await prompter.prompt({ title: 'Rename group', label: 'Group name', initialValue: 'Kiosk fleet', maxLength: 40 });
            setResult(value === null ? 'Rename cancelled' : `Renamed to ${value}`);
          }}
        >
          Rename group
        </Button>
        <Button
          variant="secondary"
          onClick={() =>
            toast('success', 'Device archived', {
              description: 'It no longer counts toward compliance.',
              action: { label: 'Undo', onClick: () => setResult('Archive undone') },
            })
          }
        >
          Archive with Undo
        </Button>
        <Menu
          label="Row actions"
          trigger={<IconButton label="Row actions" icon={<IconMore />} variant="secondary" />}
          items={[
            { id: 'edit', label: 'Edit', onSelect: () => setResult('Edit chosen') },
            { id: 'dup', label: 'Duplicate', onSelect: () => setResult('Duplicate chosen') },
            { id: 'del', label: 'Delete', danger: true, onSelect: () => setResult('Delete chosen') },
          ]}
        />
        <Button ref={popRef} variant="secondary" aria-expanded={pop} onClick={() => setPop((v) => !v)}>
          Popover
        </Button>
      </div>
      <p className="gallery-note" role="status">
        Last result: {result}
      </p>
      <Popover open={pop} onClose={() => setPop(false)} anchorRef={popRef} label="Popover example">
        <div className="gallery-popover">
          <p className="gallery-note">Popovers close on Escape or an outside click.</p>
          <Button size="sm" variant="secondary" onClick={() => setPop(false)}>
            Done
          </Button>
        </div>
      </Popover>
      <Modal
        open={modal}
        onClose={() => setModal(false)}
        title="Edit device"
        meta={<Badge tone="warning">Unsaved</Badge>}
        subtitle="Changes apply on the next check-in."
        icon={<IconInfo />}
        hue="blue"
        onSubmit={() => setModal(false)}
        primaryAction={{ label: 'Save' }}
      >
        <ModalSection title="Identity" description="How the device appears in lists.">
          <Field label="Display name">
            <Input defaultValue="Lab kiosk 4" data-autofocus="" />
          </Field>
        </ModalSection>
        <ModalSection title="Ring">
          <Field label="Update ring">
            <Select defaultValue="pilot" options={[{ value: 'pilot', label: 'Pilot' }, { value: 'broad', label: 'Broad' }]} />
          </Field>
        </ModalSection>
      </Modal>
      <Modal open={sheet} onClose={() => setSheet(false)} title="Filters" variant="sheet" primaryAction={{ label: 'Apply', onClick: () => setSheet(false) }}>
        <Field label="Owner">
          <Input placeholder="Any owner" />
        </Field>
      </Modal>
      <Modal open={bare} onClose={() => setBare(false)} title="Device photo" hideHead cancelLabel={null} data-gallery="headless">
        <EmptyState title="No photo yet" body="The title still names this dialog for screen readers." />
      </Modal>
      <Modal open={wide} onClose={() => setWide(false)} title="Compare rings" size="wide" cancelLabel="Close">
        <p className="modal-text">Wide dialogs hold tables and side by side forms. Size full fills the viewport.</p>
      </Modal>
      {confirmer.dialog}
      {prompter.dialog}
    </div>
  );
}

function ChromeSpecimen({ releases, version }: { releases: readonly ReleaseNote[]; version: string }) {
  return (
    <div className="gallery-stack">
      <AnnouncementStack
        announcements={[
          {
            id: 'gallery-sync',
            tone: 'critical',
            title: 'Directory sync is failing',
            body: 'New accounts are not appearing. This clears itself once a sync succeeds.',
            dismissible: false,
            action: (
              <a className="announce-link" href="#specimen-chrome">
                View sync status
              </a>
            ),
          },
          {
            id: 'gallery-maint',
            tone: 'warning',
            title: 'Maintenance on Saturday',
            body: 'Sign-in may be slow between 06:00 and 07:00.',
            meta: 'Posted today',
            action: (
              <Button size="sm" variant="secondary">
                Add to calendar
              </Button>
            ),
          },
          { id: 'gallery-new', tone: 'info', title: 'New reports are live', body: 'Compliance trends now cover 90 days.' },
        ]}
      />
      <div className="gallery-row">
        <SearchTrigger />
        <SearchTrigger compact />
        <Button variant="secondary" onClick={() => openCommandPalette()}>
          Open the palette
        </Button>
        <span className="gallery-note">
          Or press <Kbd>Ctrl</Kbd> <Kbd>K</Kbd>, and <Kbd>?</Kbd> for the shortcut sheet.
        </span>
      </div>
      <div className="gallery-build">
        <BuildCard version={version} releases={releases} subtitle="Built today" storageKey="gallery.build.seen" />
      </div>
    </div>
  );
}

function ChartsSpecimen() {
  const theme = useChartTheme();
  const hues = useCategoricalHues();
  const values = [42, 68, 35, 80, 54, 61];
  return (
    <div className="gallery-grid gallery-charts">
      <Card>
        <CardHead title="Series palette" subtitle="Six categorical hues minus the one the accent withholds" level={3} />
        <svg className="gallery-chart" viewBox="0 0 240 120" role="img" aria-label={`Bar chart with ${theme.series.length} series`}>
          <line x1="0" y1="110" x2="240" y2="110" stroke={theme.grid} />
          {theme.series.map((color, i) => (
            <rect key={color + i} x={10 + i * 38} y={110 - (values[i] ?? 0)} width="26" height={values[i] ?? 0} rx="4" fill={color} />
          ))}
        </svg>
      </Card>
      <Card>
        <CardHead title="Hues for data" subtitle="The legend for the chart, in series order" level={3} />
        <CardBody>
          <ol className="gallery-hues" aria-label="Hues for data in series order">
            {hues.map((h, i) => (
              <li key={h} className="gallery-hue">
                <Pill hue={h}>{h}</Pill>
                <span className="gallery-hue-track" aria-hidden="true">
                  <span className="gallery-hue-bar" data-hue={h} style={{ width: `${values[i] ?? 0}%` }} />
                </span>
                <span className="gallery-note">{values[i] ?? 0}</span>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>
    </div>
  );
}

/* A neutral sample picture for the art mark specimen: a plain tower, drawn here, no product art. */
const SAMPLE_ART = `data:image/svg+xml,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><path d="M104 232 L116 96 H140 L152 232 Z" fill="#9fb0cc"/>' +
    '<rect x="96" y="226" width="64" height="12" rx="4" fill="#7c8eb0"/><rect x="108" y="64" width="40" height="36" rx="6" fill="#c9d4e8"/>' +
    '<rect x="116" y="74" width="24" height="16" rx="3" fill="#5c6f94"/><path d="M104 64 L128 36 L152 64 Z" fill="#b4c2dc"/></svg>',
)}`;

const SAMPLE_ANCHORS: ArtAnchors = {
  focus: [50, 30],
  reach: 44,
  spark: [60, 18],
  pivot: [50, 90],
  arcs: { radii: [12, 20, 28, 36], from: 300, span: 120 },
  box: [38, 36, 24, 28],
  feed: { rect: [42, 40, 16, 20], slide: [18, 0] },
};

const ART_HUES: Record<string, [string, string]> = {
  beacon: ['blue', 'teal'],
  glint: ['violet', 'yellow'],
  signal: ['teal', 'blue'],
  ring: ['amber', 'yellow'],
  scan: ['green', 'teal'],
  lightning: ['blue', 'teal'],
  fire: ['amber', 'red'],
};

function ArtMarkSpecimen() {
  return (
    <div className="gallery-stack">
      <p className="gallery-note">
        Each recipe on its host. The effect shows only inside an element that carries data-art-host and data-art-live, or on hover and keyboard focus of the host.
      </p>
      <ul className="gallery-art-grid" aria-label="Art mark effect recipes">
        {Object.keys(ART_EFFECTS).map((name) => {
          const [hue, hot] = ART_HUES[name] ?? ['blue', 'blue'];
          return (
            <li key={name} className="gallery-art-cell" data-art-host data-art-live="">
              <ArtMark src={SAMPLE_ART} effect={name} hue={hue} hot={hot} anchors={SAMPLE_ANCHORS} size={72} title={`${name} effect on a sample tower`} />
              <span className="gallery-note">{name}</span>
            </li>
          );
        })}
        <li className="gallery-art-cell" data-art-host data-art-live="soft">
          <ArtMark src={SAMPLE_ART} effect="beacon" hue="blue" hot="teal" anchors={SAMPLE_ANCHORS} size={40} title="Calm beacon, small" />
          <span className="gallery-note">soft, 40 px</span>
        </li>
        <li className="gallery-art-cell" data-art-host>
          <ArtMark src={SAMPLE_ART} effect="beacon" hue="blue" hot="teal" anchors={SAMPLE_ANCHORS} size={72} title="Still picture until hovered" />
          <span className="gallery-note">still, hover to wake</span>
        </li>
      </ul>
    </div>
  );
}

const TYPE_ROLES: ReadonlyArray<{ name: string; cls: string; sample: string }> = [
  { name: 'display', cls: 'gallery-type-display', sample: 'Display figure' },
  { name: 'title', cls: 'gallery-type-title', sample: 'Page title' },
  { name: 'stat', cls: 'gallery-type-stat', sample: '1,284 active' },
  { name: 'subtitle', cls: 'gallery-type-subtitle', sample: 'A subtitle under a title' },
  { name: 'label', cls: 'gallery-type-label', sample: 'Field label' },
  { name: 'caption', cls: 'gallery-type-caption', sample: 'A caption below a figure' },
  { name: 'eyebrow', cls: 'gallery-type-eyebrow', sample: 'Eyebrow' },
  { name: 'mono', cls: 'gallery-type-mono', sample: 'id-0042 /path/to/item' },
  { name: 'mono-caption', cls: 'gallery-type-mono-caption', sample: 'id-0042 meta line' },
];

const FONT_WEIGHTS = [
  { name: 'medium', token: '--fw-medium', cls: 'gallery-fw-medium' },
  { name: 'semibold', token: '--fw-semibold', cls: 'gallery-fw-semibold' },
  { name: 'bold', token: '--fw-bold', cls: 'gallery-fw-bold' },
  { name: 'extrabold', token: '--fw-extrabold', cls: 'gallery-fw-extrabold' },
];

function TypeRolesSpecimen() {
  return (
    <>
      <ul className="gallery-type-roles" aria-label="Type roles">
        {TYPE_ROLES.map((role) => (
          <li key={role.name} className="gallery-type-row">
            <span className="gallery-type-name">{role.name}</span>
            <span className={role.cls}>{role.sample}</span>
          </li>
        ))}
      </ul>
      <ul className="gallery-type-roles gallery-weights" aria-label="Font weights">
        {FONT_WEIGHTS.map((w) => (
          <li key={w.name} className="gallery-type-row">
            <span className="gallery-type-name">{w.token}</span>
            <span className={w.cls}>The quick brown fox 0123456789</span>
          </li>
        ))}
      </ul>
    </>
  );
}

interface DemoDevice {
  name: string;
  owner: string;
  status: string;
}

/** The record preview: a registry with two record types, chips that open the labelled dialog, and a type whose loader fails. */
function RecordPreviewSpecimen() {
  const [registry] = useState(() => {
    const reg = createRecordRegistry();
    const pause = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
    reg.register<DemoDevice>('device', {
      label: 'Device',
      load: async (id) => {
        await pause(600);
        return { name: `Kiosk ${id}`, owner: 'Front desk', status: 'Healthy' };
      },
      title: (data) => data.name,
      render: (data) => (
        <dl className="gallery-stack">
          <div><dt className="gallery-note">Owner</dt><dd>{data.owner}</dd></div>
          <div><dt className="gallery-note">Status</dt><dd>{data.status}</dd></div>
        </dl>
      ),
      href: (id) => `#device-${id}`,
    });
    reg.register<never>('report', {
      label: 'Report',
      load: async () => {
        await pause(300);
        throw new Error('The report service did not answer.');
      },
      render: () => null,
    });
    return reg;
  });
  return (
    <RecordPreviewProvider registry={registry}>
      <div className="gallery-stack">
        <p className="gallery-note">A chip opens the preview for its type. The device loads, the report fails and offers Retry, and the last chip has no registered type so it stays plain text.</p>
        <div className="gallery-row">
          <RecordChip type="device" id="14">Kiosk 14</RecordChip>
          <RecordChip type="device" id="22">Kiosk 22</RecordChip>
          <RecordChip type="report" id="q3">Quarterly report</RecordChip>
          <RecordChip type="invoice" id="7">Invoice 7</RecordChip>
        </div>
      </div>
    </RecordPreviewProvider>
  );
}

/** The record preview seed: the dialog paints cached data at once, the live load merges over it and a body edit reloads. */
function RecordPreviewSeedSpecimen() {
  const [registry] = useState(() => {
    const reg = createRecordRegistry();
    const pause = (ms: number) => new Promise<void>((resolve) => window.setTimeout(resolve, ms));
    let revision = 1;
    reg.register<DemoDevice & { cachedNote?: string }>('seeded-device', {
      label: 'Device',
      seed: (ref, context) => ({ name: `Kiosk ${ref.id}`, owner: 'Loading owner', status: 'Cached', ...(context?.['from'] ? { cachedNote: `Opened from ${String(context['from'])}` } : {}) }),
      load: async (id) => {
        await pause(1200);
        return { name: `Kiosk ${id}`, owner: 'Front desk', status: `Healthy, revision ${revision}` };
      },
      merge: (seed, live) => ({ ...seed, ...live }),
      title: (data) => data.name,
      render: (data, context) => (
        <div className="gallery-stack">
          <dl className="gallery-stack">
            <div><dt className="gallery-note">Owner</dt><dd>{data.owner}</dd></div>
            <div><dt className="gallery-note">Status</dt><dd>{data.status}</dd></div>
            {data.cachedNote ? <div><dt className="gallery-note">Context</dt><dd>{data.cachedNote}</dd></div> : null}
          </dl>
          <div>
            <button
              type="button"
              className="btn"
              data-variant="secondary"
              data-size="md"
              onClick={() => {
                revision += 1;
                context.reload();
              }}
            >
              Save an edit
            </button>
          </div>
        </div>
      ),
    });
    return reg;
  });
  return (
    <RecordPreviewProvider registry={registry}>
      <div className="gallery-stack">
        <p className="gallery-note">The dialog paints the cached record at once and marks the body busy while the live load runs, then merges the live data over it. Save an edit reloads the record without the skeleton.</p>
        <div className="gallery-row">
          <RecordChip type="seeded-device" id="31" context={{ from: 'the fleet table' }}>Kiosk 31</RecordChip>
          <RecordChip type="seeded-device" id="32">Kiosk 32</RecordChip>
        </div>
      </div>
    </RecordPreviewProvider>
  );
}

function CrashingPage({ crash }: { crash: boolean }) {
  if (crash) throw new Error('The chart data was missing a series.');
  return <p className="gallery-note">This page renders normally.</p>;
}

/** The page scoped error boundary: the crash stays in the page, and the next page clears it. */
function PageCrashSpecimen() {
  const [path, setPath] = useState('/reports');
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <Button variant="secondary" onClick={() => setPath('/reports')}>
          Go to the broken page
        </Button>
        <Button variant="secondary" onClick={() => setPath('/home')}>
          Go to a healthy page
        </Button>
        <span className="gallery-note">Current page: {path}</span>
      </div>
      <PageErrorBoundary resetKey={path} onError={() => undefined}>
        <CrashingPage crash={path === '/reports'} />
      </PageErrorBoundary>
    </div>
  );
}

const HOME_TOOLS: HomeTool[] = [
  { id: 'reports', name: 'Reports', basePath: '/reports', hue: 'teal' },
  { id: 'devices', name: 'Devices', basePath: '/devices', hue: 'violet' },
  { id: 'tickets', name: 'Tickets', basePath: '/tickets' },
];

/** The hub home: the three zones with the feed, actions and pinned blocks, and the header pin control sharing one store. */
const SNIPPETS = [
  { id: 'welcome', title: 'Welcome note', body: 'Hello, and thanks for getting in touch. Here is what happens next.' },
  { id: 'followup', title: 'Follow up', body: 'Checking in on the request from last week. Is there anything you still need from us?' },
  { id: 'closing', title: 'Closing note', body: 'This is now complete. Reply here if anything looks wrong and we will reopen it.' },
];

const REORDER_TILES = [
  { id: 'open', label: 'Open items', value: 12, hint: 'Waiting for a decision' },
  { id: 'done', label: 'Done this week', value: 48, hint: 'Up from last week' },
  { id: 'late', label: 'Overdue', value: 3, hint: 'Past the due date' },
  { id: 'new', label: 'New today', value: 7, hint: 'Added since midnight' },
];

function PaletteTilesSpecimen() {
  const [text, setText] = useState('');
  const [store] = useState(() => createMemoryTileOrderStore(['done', 'gone', 'open']));
  const reorder = useTileReorder({ catalog: REORDER_TILES.map(({ id, label }) => ({ id, label })), store });
  const tileById = new Map(REORDER_TILES.map((t) => [t.id, t] as const));
  const items: PaletteItem[] = SNIPPETS.map((n) => ({ id: n.id, label: n.title, kind: 'Template', onSelect: () => setText(n.body) }));
  return (
    <div className="gallery-stack">
      <Field label="Reply" hint="Cmd or Ctrl and K in this box searches templates and previews them. Anywhere else it opens the page search.">
        <div {...paletteScope('templates')}>
          <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </div>
      </Field>
      <CommandPalette
        scope="templates"
        label="Templates"
        placeholder="Search templates"
        shortcutDescription="Search templates"
        items={items}
        previewLabel="Template preview"
        preview={(item) => (
          <p className="gallery-note">{SNIPPETS.find((n) => n.id === item?.id)?.body ?? 'Pick a template to preview it.'}</p>
        )}
      />
      <p className="gallery-note">Drag a tile, or focus it and hold Alt with an arrow key. The order is kept in the store.</p>
      <div className="gallery-grid" aria-label="Dashboard tiles" role="group">
        {reorder.tiles.map((t) => {
          const tile = tileById.get(t.id) as (typeof REORDER_TILES)[number];
          return (
            <div key={t.id} {...reorder.tileProps(t.id)}>
              <StatTile label={tile.label} value={tile.value} hint={tile.hint} />
            </div>
          );
        })}
      </div>
      <TileReorderStatus reorder={reorder} />
    </div>
  );
}

const RANK_ROWS: ReadonlyArray<{ id: string; label: string; description: string; badge: string; group: string }> = [
  { id: 'rk1', label: 'Quarterly summary', description: 'Totals and trends for the last three months', badge: 'Draft', group: 'Reports' },
  { id: 'rk2', label: 'Weekly summary', description: 'What changed since Monday', badge: 'Ready', group: 'Reports' },
  { id: 'rk3', label: 'Summary export', description: 'Download the current view as a file', badge: 'New', group: 'Actions' },
  { id: 'rk4', label: 'Archive old items', description: 'Moves closed items out of the main list', badge: 'Slow', group: 'Actions' },
];

function PaletteRankSpecimen() {
  const [group, setGroup] = useState('All');
  const items: PaletteItem[] = RANK_ROWS.filter((r) => group === 'All' || r.group === group).map((r) => ({
    id: r.id,
    label: r.label,
    kind: r.group,
    description: r.description,
    badge: r.badge,
    onSelect: () => undefined,
  }));
  // A host ranking: a label that starts with the query comes before one that only contains it.
  const rank = (query: string, list: readonly PaletteItem[]) => {
    const q = query.trim().toLowerCase();
    if (!q) return list;
    const starts = list.filter((i) => i.label.toLowerCase().startsWith(q));
    const rest = list.filter((i) => !i.label.toLowerCase().startsWith(q) && i.label.toLowerCase().includes(q));
    return [...starts, ...rest];
  };
  return (
    <div className="gallery-stack">
      <p className="gallery-note">A palette with its own ranking, a filter toolbar, a description line and a status mark per row.</p>
      <div className="gallery-row">
        <Button variant="secondary" onClick={() => openScopedPalette('rank-demo')}>
          Open ranked palette
        </Button>
      </div>
      <CommandPalette
        scope="rank-demo"
        label="Ranked search"
        placeholder="Search summaries and actions"
        shortcutDescription="Search the ranked list"
        items={items}
        rank={rank}
        limit={10}
        toolbarLabel="Kind"
        toolbar={['All', 'Reports', 'Actions'].map((g) => (
          <Button key={g} size="sm" variant={group === g ? 'primary' : 'secondary'} aria-pressed={group === g} onClick={() => setGroup(g)}>
            {g}
          </Button>
        ))}
      />
    </div>
  );
}

function TileEdgeSpecimen() {
  const [store] = useState(() => createMemoryTileOrderStore(['done', 'gone', 'open']));
  const reorder = useTileReorder({ catalog: REORDER_TILES.map(({ id, label }) => ({ id, label })), store, edge: true });
  const tileById = new Map(REORDER_TILES.map((t) => [t.id, t] as const));
  return (
    <div className="gallery-stack">
      <p className="gallery-note">Drag a tile. The half of the tile it will land in is tinted, and the empty space after the last tile moves it last.</p>
      <div className="gallery-grid" aria-label="Tiles with edge drops" role="group">
        {reorder.tiles.map((t) => {
          const tile = tileById.get(t.id) as (typeof REORDER_TILES)[number];
          return (
            <div key={t.id} {...reorder.tileProps(t.id)}>
              <StatTile label={tile.label} value={tile.value} hint={tile.hint} />
            </div>
          );
        })}
        <div {...reorder.endZoneProps} />
      </div>
      <TileReorderStatus reorder={reorder} />
    </div>
  );
}

function HubHomeSpecimen() {
  const [pins] = useState(() =>
    createMemoryPinsStore({
      pins: [
        { moduleId: 'reports', route: '/runs', label: 'Scheduled runs' },
        { moduleId: 'devices', route: '/fleet', label: 'Fleet overview' },
      ],
    }),
  );
  const [recents] = useState<Recent[]>(() => {
    const now = Date.now();
    return [
      { moduleId: 'tickets', route: '/queue', label: 'Open queue', at: now - 2 * 3600 * 1000 },
      { moduleId: 'reports', route: '/runs', label: 'Scheduled runs', at: now - 5 * 3600 * 1000 },
      { moduleId: 'devices', route: '/compliance', label: 'Compliance', at: now - 26 * 3600 * 1000 },
    ];
  });
  const [opened, setOpened] = useState('');
  const [reports, devices, tickets] = HOME_TOOLS as [HomeTool, HomeTool, HomeTool];
  const blocks = {
    waiting: (
      <FeedBlock
        id="waiting"
        title="Waiting on you"
        subtitle="Items that need your action"
        icon={<HueTile hue="amber"><IconWarning size={18} /></HueTile>}
        hideZero
        go={setOpened}
        emptyTitle="Nothing is waiting on you"
        emptyBody="No approvals and no failed items of yours are open."
        sources={[
          {
            tool: tickets,
            status: 'ready',
            items: [
              { key: 'approvals', label: 'Approvals', detail: 'Waiting for a decision', value: 3, tone: 'warning', route: '/approvals' },
              { key: 'failed', label: 'Failed imports', value: 0, route: '/imports' },
            ],
          },
          { tool: devices, status: 'error' },
        ]}
      />
    ),
    actions: (
      <ActionsBlock
        go={setOpened}
        actions={[
          { key: 'new', tool: reports, label: 'New report', route: '/new', icon: <IconPlus size={14} /> },
          { key: 'scan', tool: devices, label: 'Scan a device', route: '/scan', icon: <IconSearch size={14} /> },
          { key: 'open', tool: tickets, label: 'Open a ticket', route: '/new', icon: <IconPlus size={14} /> },
        ]}
      />
    ),
    live: (
      <FeedBlock
        id="live"
        title="Live operations"
        subtitle="What is running right now"
        icon={<HueTile hue="green"><IconRefresh size={18} /></HueTile>}
        go={setOpened}
        emptyTitle="Nothing live to show"
        emptyBody="No operations are active in the modules you use."
        sources={[
          {
            tool: reports,
            status: 'ready',
            items: [
              { key: 'runs', label: 'Runs in progress', detail: 'Started in the last hour', value: 12, tone: 'info', route: '/runs' },
              { key: 'health', label: 'Services healthy', value: '8/8', tone: 'success', route: '/health' },
            ],
          },
          { tool: devices, status: 'ready', items: [{ key: 'unknown', label: 'Sync status', detail: 'Could not be read', value: null, route: '/sync' }] },
        ]}
      />
    ),
    fleet: (
      <FeedBlock
        id="fleet"
        title="Fleet snapshot"
        subtitle="Coverage, updates and device health"
        icon={<HueTile hue="blue"><IconInfo size={18} /></HueTile>}
        go={setOpened}
        emptyTitle="No fleet data yet"
        emptyBody="Devices has not reported counts."
        sources={[{ tool: devices, status: 'ready', items: [{ key: 'cov', label: 'Coverage', detail: 'Devices reporting', value: 1284, tone: 'success', route: '/coverage' }, { key: 'stale', label: 'Out of date', value: 41, tone: 'danger', route: '/stale' }] }]}
      />
    ),
    pinned: <PinnedBlock store={pins} tools={HOME_TOOLS} recents={recents} go={setOpened} />,
  };
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <span className="gallery-note">Header pin control on a page of Reports:</span>
        <PinButton store={pins} moduleId="reports" route="/new" label="New report" />
        <span className="gallery-note">Denied pins read renders nothing:</span>
        <PinButton store={createMemoryPinsStore({ denied: true })} moduleId="reports" route="/new" label="New report" />
        <span className="gallery-note" aria-hidden="true">
          <IconPinOff size={14} /> Unpin sits on every pinned row.
        </span>
      </div>
      <HubHome blocks={blocks} label="Hub home example" />
      {opened ? (
        <p className="gallery-note" role="status">
          Opened {opened}
        </p>
      ) : null}
    </div>
  );
}

function SurfacesSpecimen() {
  const steps = ['bg-canvas', 'surface-1', 'surface-2', 'surface-3', 'surface-4', 'surface-5'] as const;
  return (
    <div className="gallery-stack">
      <ul className="gallery-ladder" aria-label="Surface ladder">
        {steps.map((step) => (
          <li key={step} className="gallery-step" data-step={step}>
            <span className="gallery-step-name">{step}</span>
            <span className="gallery-step-ink gallery-ink-primary">Primary ink</span>
            <span className="gallery-step-ink gallery-ink-secondary">Secondary ink</span>
            <span className="gallery-step-ink gallery-ink-tertiary">Tertiary ink</span>
            {step !== 'surface-4' && step !== 'surface-5' ? <span className="gallery-step-ink gallery-ink-quaternary">Quaternary ink</span> : null}
          </li>
        ))}
      </ul>
      <div className="gallery-row">
        <span className="hue-chip hue-blue">Blue chip</span>
        <span className="hue-chip hue-green">Green chip</span>
        <span className="hue-chip hue-amber">Amber chip</span>
        <span className="hue-chip hue-red">Red chip</span>
        <span className="hue-chip hue-violet">Violet chip</span>
        <span className="hue-chip">Accent chip</span>
      </div>
      <div className="gallery-grid">
        <Card>
          <CardHead title="Card with sheen" subtitle="A hairline ring, a top light and a faint sheen" level={3} icon={<IconSparkle />} />
          <CardBody>
            <p className="gallery-note">The card face separates from the page by fill, ring and top light together.</p>
          </CardBody>
        </Card>
        <Card elevated>
          <CardHead title="Raised card" subtitle="One step higher" level={3} icon={<IconInfo />} />
          <CardBody>
            <p className="gallery-note">The page header above wears the accent wash.</p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

/* Wave 2: selection, list and error states, form sections, data charts, the node graph and the API
   reference. */

function SelectionSpecimen() {
  // A plain state pair works as a Table selection; useRowSelection adds count, ids and toggleAll.
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(['r1', 'r2']));
  return (
    <Card>
      <CardHead title="Device groups" subtitle="Select all acts on the rows on screen. Offline groups cannot be picked." level={3} />
      <SelectionBar
        count={selected.size}
        onClear={() => setSelected(new Set())}
        actions={[
          { label: 'Restart', onClick: () => undefined },
          { label: 'Retire', onClick: () => undefined, danger: true },
        ]}
      />
      <Table
        caption="Device groups to act on"
        columns={COLUMNS}
        rows={ROWS}
        rowKey={(r) => r.id}
        selection={{ selected, onSelectedChange: setSelected }}
        isRowSelectable={(r) => r.status !== 'Offline'}
        selectionLabel={(r) => `Select ${r.name}`}
      />
      <ListFooter shown={ROWS.length} total={38} updatedAt={Date.now() - 90_000}>
        <Pagination page={1} pageSize={4} total={38} unit="groups" onNext={() => undefined} />
      </ListFooter>
    </Card>
  );
}

/* Filter panel and bulk run: typed cells emitting a neutral clause list, and a selection bar that
   shows a bounded bulk run. Everything starts still, so the specimen is the same on every load. */

const OWNER_NAMES = ['Avery Quinn', 'Blake Ortiz', 'Casey Lin', 'Devon Park', 'Emery Shah'];

const FILTER_FIELDS: FilterField[] = [
  { key: 'name', label: 'Name', type: 'text', placeholder: 'Contains' },
  { key: 'size', label: 'Size', type: 'number' },
  { key: 'seen', label: 'Last seen', type: 'date' },
  {
    key: 'state',
    label: 'State',
    type: 'select',
    options: [
      { value: 'online', label: 'Online' },
      { value: 'offline', label: 'Offline' },
    ],
  },
  {
    key: 'tags',
    label: 'Tags',
    type: 'multiselect',
    options: [
      { value: 'kiosk', label: 'Kiosk' },
      { value: 'east', label: 'East' },
      { value: 'lab', label: 'Lab' },
    ],
  },
  { key: 'managed', label: 'Managed', type: 'boolean' },
  {
    key: 'owner',
    label: 'Owner',
    type: 'lookup',
    load: async (query) =>
      OWNER_NAMES.filter((n) => n.toLowerCase().includes(query.trim().toLowerCase())).map((n) => ({ value: n.toLowerCase().replace(' ', '.'), label: n })),
  },
  {
    key: 'reviewers',
    label: 'Reviewers',
    type: 'lookup',
    multiple: true,
    load: async (query) =>
      OWNER_NAMES.filter((n) => n.toLowerCase().includes(query.trim().toLowerCase())).map((n) => ({ value: n.toLowerCase().replace(' ', '.'), label: n })),
  },
];

const FINISHED_RUN: BulkRunState = {
  status: 'done',
  total: 5,
  done: 5,
  succeeded: 3,
  failed: 2,
  active: 0,
  errors: [
    { key: 'group-2', index: 1, message: 'The device did not answer' },
    { key: 'group-4', index: 3, message: 'Refused by policy' },
  ],
};

const RUNNING_RUN: BulkRunState = { status: 'running', total: 12, done: 5, succeeded: 5, failed: 0, active: 3, errors: [] };

function FilterBulkSpecimen() {
  const [clauses, setClauses] = useState<FilterClause[]>([]);
  const items = ['group-1', 'group-2', 'group-3', 'group-4', 'group-5'];
  const bulk = useBulkRun<string>(
    (item, signal) =>
      new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => (item === 'group-2' || item === 'group-4' ? reject(new Error('The action was refused')) : resolve()), 600);
        signal.addEventListener('abort', () => {
          clearTimeout(timer);
          resolve();
        });
      }),
    { concurrency: 2, itemKey: (item) => item },
  );
  return (
    <div className="gallery-stack">
      <div className="gallery-grid">
        <Card>
          <CardHead title="Filter panel" subtitle="Typed cells, a lookup and a neutral clause list" level={3} />
          <CardBody>
            <FilterPanel fields={FILTER_FIELDS} value={clauses} onApply={setClauses} />
            <pre className="gallery-note" aria-label="Emitted clauses">
              {clauses.length === 0 ? 'No filters applied' : JSON.stringify(clauses)}
            </pre>
          </CardBody>
        </Card>
        <Card>
          <CardHead title="Bulk run" subtitle="Two at a time, with progress, errors and Cancel" level={3} />
          <CardBody>
            <div className="gallery-stack">
              <SelectionBar
                count={items.length}
                onClear={bulk.reset}
                actions={[{ label: 'Run on all', onClick: () => void bulk.run(items), disabled: bulk.state.status === 'running' }]}
                run={bulk.state}
                onCancel={bulk.cancel}
                itemNoun="groups"
                name="Selection, live run"
              />
              <SelectionBar count={12} onClear={() => undefined} actions={[]} run={RUNNING_RUN} onCancel={() => undefined} itemNoun="groups" name="Selection, running" />
              <SelectionBar count={5} onClear={() => undefined} actions={[]} run={FINISHED_RUN} itemNoun="groups" name="Selection, finished with errors" />
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

const LIST_ITEMS = Array.from({ length: 36 }, (_, i) => ({
  id: `i${i + 1}`,
  name: `Item ${String(i + 1).padStart(2, '0')}`,
  note: i % 3 === 0 ? 'Waiting for a review' : 'Up to date',
  group: i % 2 === 0 ? 'Group A' : 'Group B',
  age: `${i + 1}d`,
}));

function ListSplitSpecimen() {
  const pager = usePagination(LIST_ITEMS.length, 6);
  const page = pager.slice(LIST_ITEMS);
  const selection = useRowSelection(page.map((r) => r.id));
  const [open, setOpen] = useState<string | null>('i2');
  const current = LIST_ITEMS.find((r) => r.id === open) ?? null;
  return (
    <Card>
      <CardHead title="List and detail" subtitle="Drag the handle or focus it and use the arrow keys. Under 720 pixels the panes stack." level={3} />
      <CardBody>
        <SplitLayout
          height="26rem"
          listLabel="Items"
          detailLabel="Item detail"
          list={
            <div className="gallery-list-pane">
              <ListTable
                caption="Items"
                rows={page}
                rowKey={(r) => r.id}
                primary={(r) => r.name}
                secondary={(r) => r.note}
                trailing={(r) => r.age}
                groupBy={(r) => r.group}
                selectedKey={open}
                onRowActivate={(r) => setOpen(r.id)}
                selection={selection}
                selectionLabel={(r) => `Select ${r.name}`}
                header="Item"
              />
              <Pagination {...pager.props} unit="items" pageSizeOptions={[6, 12, 24]} />
            </div>
          }
          detail={
            current ? (
              <div className="gallery-stack">
                <h3 className="gallery-note">{current.name}</h3>
                <p className="gallery-note">{current.note}. Opened from the list, separate from the checked rows.</p>
              </div>
            ) : null
          }
        />
      </CardBody>
    </Card>
  );
}

function StatesSpecimen() {
  const [tags, setTags] = useState(['production', 'east', 'kiosk']);
  return (
    <div className="gallery-stack">
      <CardHead
        variant="panel"
        level={3}
        title="Panel head"
        subtitle="CardHead variant panel: the head of a page region that is not inside a card"
        controls={
          <Button variant="secondary" size="sm">
            Export
          </Button>
        }
      />
      <div className="gallery-grid">
        <Card>
          <CardHead title="A failed read" level={3} />
          <CardBody>
            <ErrorState error={new Error('The inventory service did not answer in time.')} onRetry={() => undefined} />
          </CardBody>
        </Card>
        <Card>
          <CardHead title="A list loading" level={3} />
          <CardBody>
            <Skeleton variant="list" count={4} label="Loading devices" />
          </CardBody>
        </Card>
        <Card>
          <CardHead title="Removable tags" subtitle="Badge with onRemove" level={3} />
          <CardBody>
            <div className="gallery-row">
              {tags.map((t) => (
                <Badge key={t} onRemove={() => setTags((all) => all.filter((x) => x !== t))}>
                  {t}
                </Badge>
              ))}
              <Badge tone="info" onRemove={() => undefined} removing>
                archived
              </Badge>
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHead title="Meters" subtitle="ProgressBar meter: a measured quantity" level={3} />
          <CardBody className="gallery-stack">
            <CardHead variant="label" level={4} title="Storage" count={3} />
            <ProgressBar meter value={38} label="Disk used, 38 percent" tone="success" />
            <ProgressBar meter value={71} label="Memory used, 71 percent" tone="warning" />
            <ProgressBar meter value={94} label="Quota spent, 94 percent" tone="danger" />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function FormSectionSpecimen() {
  const { confirm, dialog } = useConfirm();
  const [result, setResult] = useState('');
  return (
    <Card>
      <CardHead title="Host settings" subtitle="FormSection groups a long form into named fieldsets" level={3} />
      <CardBody className="gallery-stack">
        <FormSection title="Identity" description="How the host is named and found on the network.">
          <Field label="Hostname">
            <Input defaultValue="edge-01" />
          </Field>
          <Field label="Role">
            <Select
              defaultValue="gateway"
              options={[
                { value: 'gateway', label: 'Gateway' },
                { value: 'worker', label: 'Worker' },
              ]}
            />
          </Field>
          <Field label="Notes" optional className="form-section-full">
            <Textarea rows={2} />
          </Field>
        </FormSection>
        <FormSection title="Danger zone" description="Typed confirmation guards an action that cannot be undone." columns={1}>
          <div className="gallery-row">
            <Button
              variant="danger"
              onClick={async () => {
                const ok = await confirm({
                  title: 'Delete edge-01?',
                  body: 'The host and its history are removed for good.',
                  confirmLabel: 'Delete',
                  danger: true,
                  requireText: 'edge-01',
                });
                setResult(ok ? 'Deleted edge-01' : 'Kept edge-01');
              }}
            >
              Delete host
            </Button>
            {result ? (
              <span className="gallery-note" role="status">
                {result}
              </span>
            ) : null}
          </div>
        </FormSection>
      </CardBody>
      {dialog}
    </Card>
  );
}

const TRAFFIC = [
  { day: 'Mon', reads: 1240, writes: 420 },
  { day: 'Tue', reads: 1810, writes: 515 },
  { day: 'Wed', reads: 1530, writes: 690 },
  { day: 'Thu', reads: 2105, writes: 640 },
  { day: 'Fri', reads: 1960, writes: 720 },
  { day: 'Sat', reads: 880, writes: 210 },
  { day: 'Sun', reads: 760, writes: 180 },
];

const TRAFFIC_SERIES = [
  { key: 'reads' as const, label: 'Reads' },
  { key: 'writes' as const, label: 'Writes' },
];

const FLEET = [
  { label: 'Healthy', value: 112 },
  { label: 'Degraded', value: 9 },
  { label: 'Offline', value: 4 },
];

const thousands = (v: number) => v.toLocaleString('en-US');

function DataChartsSpecimen() {
  return (
    <div className="gallery-grid gallery-charts">
      <Card>
        <CardHead title="Requests" subtitle="LineChart, two series" level={3} />
        <CardBody>
          <LineChart data={TRAFFIC} x="day" series={TRAFFIC_SERIES} label="Requests per day" height={200} formatValue={thousands} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Reads" subtitle="AreaChart" level={3} />
        <CardBody>
          <AreaChart data={TRAFFIC} x="day" series={TRAFFIC_SERIES.slice(0, 1)} label="Reads per day" height={200} formatValue={thousands} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Grouped" subtitle="BarChart" level={3} />
        <CardBody>
          <BarChart data={TRAFFIC} x="day" series={TRAFFIC_SERIES} label="Reads and writes per day" height={200} formatValue={thousands} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Stacked" subtitle="BarChart stacked" level={3} />
        <CardBody>
          <BarChart data={TRAFFIC} x="day" series={TRAFFIC_SERIES} label="Total requests per day" height={200} stacked formatValue={thousands} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Fleet health" subtitle="DonutChart" level={3} />
        <CardBody>
          <DonutChart data={FLEET} label="Devices by health" center="125" centerLabel="devices" size={160} />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Load" subtitle="Gauge, thresholds colour the arc" level={3} />
        <CardBody className="gallery-stack">
          <div className="gallery-row">
            <Gauge value={34} label="Healthy" thresholds={{ warning: 60, danger: 90 }} formatValue={(v) => `${v}%`} width={140} />
            <Gauge value={72} label="Warning" thresholds={{ warning: 60, danger: 90 }} formatValue={(v) => `${v}%`} width={140} />
            <Gauge value={96} label="Critical" thresholds={{ warning: 60, danger: 90 }} formatValue={(v) => `${v}%`} width={140} />
          </div>
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Progress" subtitle="RingProgress, label and sub label" level={3} />
        <CardBody className="gallery-stack">
          <RingProgress value={87} label="Patched" subLabel="109 of 125 devices" />
          <RingProgress value={42} label="Quota used" subLabel="Warns at 60" thresholds={{ warning: 60, danger: 90 }} />
          <RingProgress value={64} label="Share of fleet" subLabel="Not a status, info tone" tone="info" />
          <RingProgress value={15} label="Coverage" subLabel="Lower is worse" thresholds={{ warning: 50, danger: 25 }} higherIsBetter />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Legend" subtitle="ChartLegend, standalone" level={3} />
        <CardBody className="gallery-stack">
          <ChartLegend items={[{ label: 'Reads' }, { label: 'Writes' }, { label: 'Limit', line: true, color: 'var(--danger)' }]} label="Series" />
        </CardBody>
      </Card>
      <Card>
        <CardHead title="Trend" subtitle="Sparkline, word sized" level={3} />
        <CardBody className="gallery-stack">
          <div className="gallery-row">
            <span className="gallery-note">Reads</span>
            <Sparkline data={TRAFFIC.map((d) => d.reads)} label="Reads, last 7 days" width={120} />
          </div>
          <div className="gallery-row">
            <span className="gallery-note">Writes</span>
            <Sparkline data={TRAFFIC.map((d) => d.writes)} label="Writes, last 7 days" width={120} area={false} />
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

const GRAPH_NODES: GraphCardNode[] = [
  { id: 'web', type: 'card', position: { x: 0, y: 70 }, data: { label: 'Web app', kind: 'Client', hue: 'blue', meta: ['SPA', 'CDN'] } },
  { id: 'api', type: 'card', position: { x: 280, y: 70 }, data: { label: 'API', kind: 'Service', hue: 'violet', detail: '3 replicas' } },
  { id: 'db', type: 'card', position: { x: 560, y: 0 }, data: { label: 'Database', kind: 'Store', hue: 'teal' } },
  { id: 'queue', type: 'card', position: { x: 560, y: 150 }, data: { label: 'Job queue', kind: 'Store', hue: 'amber', dashed: true } },
];

const GRAPH_EDGES: Edge[] = [
  graphEdge({ id: 'web-api', source: 'web', target: 'api', sourceHandle: 'right', targetHandle: 'left', label: 'HTTPS', twoWay: true }),
  graphEdge({ id: 'api-db', source: 'api', target: 'db', sourceHandle: 'right', targetHandle: 'left', hue: 'teal' }),
  graphEdge({ id: 'api-queue', source: 'api', target: 'queue', sourceHandle: 'right', targetHandle: 'left', hue: 'amber', dashed: true }),
];

function GraphSpecimen() {
  return (
    <Card>
      <CardHead title="Service map" subtitle="Graph: React Flow with the kit node card and edges" level={3} />
      <Graph label="Service map" readOnly defaultNodes={GRAPH_NODES} defaultEdges={GRAPH_EDGES} height={300} />
    </Card>
  );
}

function ApiReferenceSpecimen() {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <CardHead
        title="Example API"
        subtitle="ApiReference: Scalar themed from the tokens. It loads when opened."
        level={3}
        controls={
          <Button variant="secondary" size="sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            {open ? 'Hide the reference' : 'Show the reference'}
          </Button>
        }
      />
      {open ? (
        <Suspense fallback={<Skeleton variant="card" label="Loading the API reference" />}>
          <ApiReferenceDemo />
        </Suspense>
      ) : null}
    </Card>
  );
}

const SWITCH_TOOLS: LauncherTool[] = [
  { id: 'reports', name: 'Reports', tagline: 'Numbers on demand', description: 'Scheduled and ad hoc reports for every team.', hue: 'teal' },
  { id: 'devices', name: 'Devices', tagline: 'The whole fleet', description: 'Every enrolled device, its health and its owner.', hue: 'blue' },
  { id: 'access', name: 'Access', tagline: 'Who can do what', description: 'Roles, groups and the grants behind them.', hue: 'violet' },
  { id: 'handbook', name: 'Handbook', tagline: 'Reference', description: 'The written standards.', external: true },
];

function ShellSwitcherSpecimen() {
  const launcher = useToolLauncher();
  const [active, setActive] = useState('reports');
  const [opened, setOpened] = useState('');
  const current = SWITCH_TOOLS.find((t) => t.id === active) ?? SWITCH_TOOLS[0];
  return (
    <div className="gallery-stack">
      <div className="gallery-row">
        <span className="gallery-note">Rail control (Rail brandSlot):</span>
        <ToolSwitchButton launcher={launcher} name={current?.name ?? 'Tools'} hue={current?.hue} />
        <span className="gallery-note">Collapsed form (mark with a corner chip, the `collapsible` rail control in a collapsed rail):</span>
        <ToolSwitchButton launcher={launcher} variant="mark" name={current?.name ?? 'Tools'} hue={current?.hue} />
        <span className="gallery-note">Large form for a screen with no rail:</span>
        <ToolSwitchButton launcher={launcher} variant="prominent" name="Reports, Devices and 2 more are open to you" hue={current?.hue} />
      </div>
      <div className="gallery-row">
        <span className="gallery-note">Account menu (Rail footer), open it for the facts, theme choice, links and Sign out:</span>
        <AccountMenu
          identity={{ name: 'Ada Lovelace', email: 'ada@example.com', role: 'Engineer' }}
          facts={[{ label: 'Access', value: 'Via the Support group' }, { label: 'Last seen', value: 'Oct 13, 8:00 AM' }]}
          links={[{ key: 'profile', label: 'My profile', href: 'https://example.com/profile' }]}
          onSignOut={() => undefined}
          placement="bottom-start"
        />
      </div>
      <p className="gallery-note">
        Press t to switch tool and / to open search, both outside text fields.
      </p>
      {opened ? (
        <p className="gallery-note" role="status">
          Opened {opened}
        </p>
      ) : null}
      <ToolLauncher
        open={launcher.open}
        onClose={launcher.close}
        origin={launcher.origin}
        tools={SWITCH_TOOLS}
        activeId={active}
        onOpen={(tool) => {
          setOpened(tool.name);
          if (!tool.external) setActive(tool.id);
        }}
      />
    </div>
  );
}

function GalleryShell({ releases, version }: { releases: readonly ReleaseNote[]; version: string }) {
  const [accent, setAccent] = useState<AppAccent>('cobalt');
  const [paletteResult, setPaletteResult] = useState('');
  const sections = ['theme', 'buttons', 'marks', 'working', 'stat-tiles', 'stats', 'choices', 'tabs', 'fields', 'table', 'empty', 'overlays', 'chrome', 'search-routing', 'charts', 'selection', 'states', 'form-sections', 'data-charts', 'graph', 'api-reference', 'surfaces', 'hub-home', 'facts', 'markdown', 'shell-switcher', 'record-preview', 'page-crash', 'palette-tiles', 'art-mark', 'filter-bulk', 'list-split', 'palette-rank', 'tile-edge', 'freshness', 'month-grid'];
  const paletteItems: PaletteItem[] = sections.map((s) => ({
    id: s,
    label: s.replace('-', ' ').replace(/^./, (c) => c.toUpperCase()),
    kind: 'Section',
    group: ['table', 'charts', 'data-charts', 'graph', 'api-reference', 'filter-bulk', 'list-split', 'stats', 'stat-tiles'].includes(s) ? 'Data' : 'Pages',
    keywords: s === 'table' ? ['grid', 'rows'] : s === 'buttons' ? ['actions'] : undefined,
    onSelect: () => {
      setPaletteResult(s);
      document.getElementById(`specimen-${s}`)?.scrollIntoView?.({ block: 'start' });
    },
  }));
  useShortcut({ id: 'gallery.top', keys: 'g h', description: 'Go to the top', group: 'Navigation', handler: () => window.scrollTo?.(0, 0) });
  return (
    <AccentProvider accent={accent}>
      <AppShell
        pathname="#gallery"
        rail={
          <Rail brandMark="K" brandName="Kit gallery" brandSlot={<span className="badge">Tool</span>} version={version} footer={<BuildCard version={version} releases={releases} />} environment="Gallery" statusText="Data refreshed just now" showVersion={false}>
            <NavGroup label="Foundations">
              <NavItem href="#specimen-theme" label="Theme" icon={<IconSparkle />} hue="brand" active />
              <NavItem href="#specimen-buttons" label="Buttons" icon={<IconPlus />} hue="blue" />
              <NavItem href="#specimen-marks" label="Marks" icon={<IconCheck />} hue="green" />
            </NavGroup>
            <NavGroup label="Patterns">
              <NavItem href="#specimen-table" label="Table" icon={<IconSearch />} hue="amber" badge={4} softBadge={2} working />
              <NavItem href="#specimen-overlays" label="Overlays" icon={<IconWarning />} hue="red" badge="New" iconBadge="dot" />
              <NavItem href="#specimen-charts" label="Charts" icon={<IconInfo />} hue="violet" />
            </NavGroup>
          </Rail>
        }
        header={
          <Header title="Kit gallery" subtitle="Every component, both themes, every accent" home={{ href: '#specimen-theme', label: 'Home' }} actions={<ThemeToggle />}>
            <SearchTrigger compact="auto" />
          </Header>
        }
        strip={
          <FeedStrip
            health={{ status: 'ok', label: 'All systems normal' }}
            items={[
              { id: 'f1', tone: 'info', title: 'New reports are live', body: 'Compliance trends now cover 90 days.' },
              { id: 'f2', tone: 'warning', title: 'Maintenance on Saturday', body: 'Sign-in may be slow.' },
              { id: 'f3', tone: 'success', title: 'Patch window closed', body: '98 percent installed.' },
            ]}
          />
        }
      >
        <PageHeader wash eyebrow="Build standards" title="Kit gallery" subtitle="The shared React kit rendered on one page." status={<Badge tone="success" dot>Tokens loaded</Badge>} />
        <Specimen id="theme" title="Theme and accent">
          <ThemeControls accent={accent} onAccent={setAccent} />
        </Specimen>
        <Specimen id="type" title="Type roles">
          <TypeRolesSpecimen />
        </Specimen>
        <Specimen id="buttons" title="Buttons">
          <ButtonsSpecimen />
        </Specimen>
        <Specimen id="marks" title="Badges, dots, tiles and tone">
          <MarksSpecimen />
        </Specimen>
        <Specimen id="working" title="Working and live states">
          <WorkingSpecimen />
        </Specimen>
        <Specimen id="stat-tiles" title="Stat tiles">
          <StatSpecimen />
        </Specimen>
        <Specimen id="freshness" title="Freshness grid">
          <FreshnessGrid
            sources={[
              { id: 'mail', label: 'Mail', state: 'fresh', ageSeconds: 120, thresholdSeconds: 3600 },
              { id: 'chat', label: 'Chat', state: 'stale', ageSeconds: 7500, thresholdSeconds: 3600 },
              { id: 'jobs', label: 'Jobs', state: 'failing', ageSeconds: 5400, thresholdSeconds: 3600, reason: 'Token expired' },
              { id: 'new', label: 'New source', state: 'unknown', ageSeconds: null, thresholdSeconds: 3600 },
            ]}
          />
        </Specimen>
        <Specimen id="stats" title="Stats">
          <StatsSpecimen />
        </Specimen>
        <Specimen id="choices" title="Checkboxes, radios and switches">
          <ChoicesSpecimen />
        </Specimen>
        <Specimen id="tabs" title="Tabs and segmented">
          <TabsSpecimen />
        </Specimen>
        <Specimen id="fields" title="Fields">
          <FieldsSpecimen />
        </Specimen>
        <Specimen id="table" title="Table and toolbar">
          <TableSpecimen />
        </Specimen>
        <Specimen id="empty" title="Empty states and loading">
          <EmptySpecimen />
        </Specimen>
        <Specimen id="wayfinding" title="Wayfinding, text and page states">
          <WayfindingSpecimen />
        </Specimen>
        <Specimen id="overlays" title="Dialogs, toasts and menus">
          <OverlaysSpecimen />
        </Specimen>
        <Specimen id="chrome" title="Required chrome">
          <ChromeSpecimen releases={releases} version={version} />
        </Specimen>
        <Specimen id="search-routing" title="Search routed to an app's own palette">
          <SearchRoutingSpecimen />
        </Specimen>
        <Specimen id="charts" title="Chart colours">
          <ChartsSpecimen />
        </Specimen>
        <Specimen id="selection" title="Row selection and list footer">
          <SelectionSpecimen />
        </Specimen>
        <Specimen id="states" title="Errors, list loading, tags and meters">
          <StatesSpecimen />
        </Specimen>
        <Specimen id="form-sections" title="Form sections and typed confirmation">
          <FormSectionSpecimen />
        </Specimen>
        <Specimen id="data-charts" title="Data charts">
          <DataChartsSpecimen />
        </Specimen>
        <Specimen id="graph" title="Node graph">
          <GraphSpecimen />
        </Specimen>
        <Specimen id="api-reference" title="API reference">
          <ApiReferenceSpecimen />
        </Specimen>
        <Specimen id="surfaces" title="Surfaces, chips and card light">
          <SurfacesSpecimen />
        </Specimen>
        <Specimen id="hub-home" title="Hub home and pinned pages">
          <HubHomeSpecimen />
        </Specimen>
        <Specimen id="facts" title="Facts and disclosure">
          <FactsSpecimen />
        </Specimen>
        <Specimen id="markdown" title="Markdown reader">
          <MarkdownSpecimen />
        </Specimen>
        <Specimen id="shell-switcher" title="Tool switcher, account menu and search key">
          <ShellSwitcherSpecimen />
        </Specimen>
        <Specimen id="lookup-and-lists" title="Combobox and list controls">
          <LookupAndListSpecimen />
        </Specimen>
        <Specimen id="record-preview" title="Record preview">
          <RecordPreviewSpecimen />
        </Specimen>
        <Specimen id="record-preview-seed" title="Record preview seed and reload">
          <RecordPreviewSeedSpecimen />
        </Specimen>
        <Specimen id="page-crash" title="Page error boundary">
          <PageCrashSpecimen />
        </Specimen>
        <Specimen id="palette-tiles" title="Palette preview and reorderable tiles">
          <PaletteTilesSpecimen />
        </Specimen>
        <Specimen id="palette-rank" title="Palette ranking, toolbar and richer rows">
          <PaletteRankSpecimen />
        </Specimen>
        <Specimen id="tile-edge" title="Tile reorder end zone and edge side">
          <TileEdgeSpecimen />
        </Specimen>
        <Specimen id="icons" title="Generic icons">
          <div className="gallery-row">
            {[
              ['Calendar', IconCalendar],
              ['Clock', IconClock],
              ['Edit', IconEdit],
              ['Eye', IconEye],
              ['Eye off', IconEyeOff],
              ['Folder', IconFolder],
              ['List', IconList],
              ['Mail', IconMail],
              ['Trash', IconTrash],
            ].map(([label, Glyph]) => {
              const G = Glyph as typeof IconClock;
              return (
                <span key={label as string} className="gallery-note">
                  <G size={20} /> {label as string}
                </span>
              );
            })}
          </div>
        </Specimen>
        <Specimen id="art-mark" title="Art mark">
          <ArtMarkSpecimen />
        </Specimen>
        <Specimen id="filter-bulk" title="Filter panel and bulk run">
          <FilterBulkSpecimen />
        </Specimen>
        <Specimen id="month-grid" title="Month grid">
          <MonthGridSpecimen />
        </Specimen>
        <Specimen id="list-split" title="List table, paging and split layout">
          <ListSplitSpecimen />
        </Specimen>
        {paletteResult ? (
          <p className="gallery-note" role="status">
            Palette opened {paletteResult}
          </p>
        ) : null}
      </AppShell>
      <CommandPalette items={paletteItems} filters={[{ id: 'Pages', label: 'Pages' }, { id: 'Data', label: 'Data' }]} />
      <TooltipLayer />
    </AccentProvider>
  );
}

export interface GalleryAppProps {
  releases?: readonly ReleaseNote[] | undefined;
  /** The kit version shown on the build card. */
  version?: string | undefined;
}

export function GalleryApp({ releases = SAMPLE_RELEASES, version = '0.1.0' }: GalleryAppProps) {
  const list = releases.length > 0 ? releases : SAMPLE_RELEASES;
  return (
    <ThemeProvider storageKey="gallery.theme">
      <ShortcutLayer>
        <Toaster>
          <GalleryShell releases={list} version={version} />
        </Toaster>
      </ShortcutLayer>
    </ThemeProvider>
  );
}

