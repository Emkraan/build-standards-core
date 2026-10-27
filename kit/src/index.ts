/* @build-standards/kit: the shared React kit for apps on this standard. Import kit.css once, after
   tokens.css and hub-layer.css. */

// Theme and accent
export { ThemeProvider, ThemeToggle, applyThemeAttribute, revealTheme, themeInitScript, useTheme } from './theme/theme';
export type { ResolvedTheme, RevealOrigin, ThemeChoice, ThemeContextValue, ThemeProviderProps, ThemeToggleProps } from './theme/theme';
export { APP_ACCENTS, AccentProvider, DEFAULT_ACCENT, getAppAccent, isAppAccent, setAppAccent } from './theme/accent';
export type { AccentProviderProps, AppAccent } from './theme/accent';

// Shell
export { AppShell } from './shell/AppShell';
export type { AppShellProps } from './shell/AppShell';
export { Rail, useNavGlider } from './shell/Rail';
export type { RailProps } from './shell/Rail';
export { NavGroup, NavItem } from './shell/nav';
export type { NavGroupProps, NavItemProps } from './shell/nav';
export { Header, PageHeader, Toolbar, formatUpdated, useNow } from './shell/Header';
export type { HeaderProps, PageHeaderProps, ToolbarProps } from './shell/Header';
export { DefaultLink, useShell } from './shell/context';
export type { KitLinkProps, LinkComponent, RailState, ShellContextValue } from './shell/context';
export { HelpButton } from './shell/HelpButton';
export type { HelpButtonProps } from './shell/HelpButton';
export { HelpDrawer, useHelpPaletteItems } from './shell/HelpDrawer';
export type { HelpDrawerProps, HelpPaletteOptions } from './shell/HelpDrawer';
export { HelpProvider, useHelp, usePageHelp } from './shell/help';
export type { HelpContextValue, HelpLinkItem, HelpProviderProps, PageHelp } from './shell/help';

// Primitives
export { Button, ButtonLink, IconButton } from './primitives/Button';
export type { ButtonLinkProps, ButtonProps, ButtonSize, ButtonVariant, IconButtonProps } from './primitives/Button';
export { Alert } from './primitives/Alert';
export type { AlertProps, AlertTone } from './primitives/Alert';
export { Card, CardBody, CardHead } from './primitives/Card';
export type { CardHeadProps, CardHeadVariant, CardProps } from './primitives/Card';
export { Badge, HueTile, Kbd, Pill, StatusDot, Tone } from './primitives/marks';
export type { BadgeProps, DotTone, HueTileProps, StatusDotProps, StatusTone, ToneProps } from './primitives/marks';
export { Spinner } from './primitives/Spinner';
export type { SpinnerProps, SpinnerSize } from './primitives/Spinner';
export { StatTile, formatCountable, parseCountable, useCountUp } from './primitives/StatTile';
export type { Countable, StatDelta, StatTileProps, StatTone } from './primitives/StatTile';
export { FreshnessGrid, formatAge, liveFreshness } from './primitives/FreshnessGrid';
export type { FreshnessGridProps, FreshnessSource, FreshnessState } from './primitives/FreshnessGrid';
export { Stat, StatRow } from './primitives/Stat';
export type { StatProps, StatRowProps, StatValueTone } from './primitives/Stat';
export { Markdown, classifyLink } from './primitives/Markdown';
export type { MarkdownProps } from './primitives/Markdown';
export { Disclosure, FactList, FactRow } from './primitives/Facts';
export type { DisclosureProps, FactListProps, FactRowProps, FactTone } from './primitives/Facts';
export { Checkbox, Radio, RadioGroup, Switch } from './primitives/Choice';
export type { CheckboxProps, ChoiceSize, RadioGroupProps, RadioOption, RadioProps, SwitchProps } from './primitives/Choice';
export { Segmented, TabPanel, Tabs, tabElementId, tabPanelId } from './primitives/Tabs';
export type { SegmentedOption, SegmentedProps, TabItem, TabPanelProps, TabsProps } from './primitives/Tabs';
export { ChipGroup } from './primitives/ChipGroup';
export type { ChipGroupProps, ChipOption } from './primitives/ChipGroup';
export { Combobox, PersonOption, UnavailableError, isUnavailableError } from './primitives/Combobox';
export type { ComboboxFreeEntry, ComboboxMessages, ComboboxProps, ComboboxRowState, PersonOptionData } from './primitives/Combobox';
export { GroupHeader, ListControls, applyGrouping, applySort, paginate, usePagedState } from './primitives/ListControls';
export type {
  GroupHeaderProps,
  ListControlOption,
  ListControlsProps,
  ListFilter,
  ListGroup,
  PagedState,
  SortDirection,
  ValueGetters,
} from './primitives/ListControls';
export { Field, FormSection, Input, Select, Textarea, useFieldControl } from './primitives/Field';
export type { FieldProps, FormSectionProps, InputProps, SelectOption, SelectProps, TextareaProps } from './primitives/Field';
export {
  ROW_INTERACTIVE_SELECTOR,
  Table,
  compareValues,
  isFromInteractiveDescendant,
  nextSort,
  sortRows,
  useRowSelection,
  useTableSort,
} from './primitives/Table';
export type {
  RowSelection,
  SortDir,
  SortState,
  SortValue,
  TableColumn,
  TableProps,
  TableRowProps,
  TableSelection,
} from './primitives/Table';
export { EmptyState, Skeleton, StickFigure } from './primitives/EmptyState';
export type { EmptyStateProps, SkeletonProps, StickFigureProps, StickPose } from './primitives/EmptyState';
export { ErrorState, errorDetail } from './primitives/ErrorState';
export { ListFooter, SelectionBar } from './primitives/ListBars';
export type { BulkAction, ListFooterProps, SelectionBarProps, SelectionBarRun } from './primitives/ListBars';
export { FilterPanel, buildFilters, draftFromFilters } from './primitives/FilterPanel';
export type {
  FilterClause,
  FilterDraft,
  FilterField,
  FilterOp,
  FilterPanelProps,
  FilterValue,
  LookupLoader,
  LookupOption,
} from './primitives/FilterPanel';
export { DEFAULT_BULK_CONCURRENCY, clampConcurrency, useBulkRun } from './lib/bulkRun';
export type { BulkRun, BulkRunError, BulkRunOptions, BulkRunResult, BulkRunState, BulkRunStatus } from './lib/bulkRun';
export type { ErrorStateProps } from './primitives/ErrorState';
export { ArtMark, artAnchorVars, isArtHue, isArtSrcSafe, useArtPaused } from './artmark/ArtMark';
export type { ArtAnchors, ArtMarkProps } from './artmark/ArtMark';
export { ART_EFFECTS, artEffectFor } from './artmark/effects';
export type { ArtEffectDef, ArtEffectName } from './artmark/effects';
export { Breadcrumb, Pagination, usePagination } from './primitives/Nav';
export type { BreadcrumbItem, BreadcrumbLinkRenderProps, BreadcrumbProps, PaginationProps, PaginationState } from './primitives/Nav';
export { ListTable, groupRows } from './primitives/ListTable';
export type { ListRowProps, ListTableProps } from './primitives/ListTable';
export { CopyButton, Mono, RelativeTime, formatRelative, freshness } from './primitives/Text';
export type { CopyButtonProps, MonoProps, RelativeTimeProps } from './primitives/Text';
export { Forbidden, NotFound } from './primitives/PageStates';
export type { ForbiddenProps, NotFoundProps } from './primitives/PageStates';
export { SearchInput } from './primitives/SearchInput';
export type { SearchInputProps } from './primitives/SearchInput';
export { MonthGrid, addDays, isoDay, monthWeeks } from './primitives/MonthGrid';
export type { MonthGridDay, MonthGridEvent, MonthGridProps, MonthGridTone } from './primitives/MonthGrid';
export { LaneBoard } from './primitives/LaneBoard';
export type { LaneBoardCard, LaneBoardLane, LaneBoardMove, LaneBoardProps } from './primitives/LaneBoard';
export { ProgressBar } from './primitives/ProgressBar';
export type { ProgressBarProps, ProgressSegment, ProgressTone } from './primitives/ProgressBar';
export { TextDiff, diffLines } from './primitives/TextDiff';
export type { DiffLine, DiffLineKind, TextDiffProps } from './primitives/TextDiff';
export { ImpersonationBanner } from './chrome/ImpersonationBanner';
export type { ImpersonationBannerProps } from './chrome/ImpersonationBanner';
export { ErrorBoundary } from './chrome/ErrorBoundary';
export { PageErrorBoundary, resetKeyChanged } from './chrome/ErrorBoundary';
export type { ErrorBoundaryProps, PageErrorBoundaryProps } from './chrome/ErrorBoundary';
export { Avatar } from './primitives/Avatar';
export type { AvatarProps } from './primitives/Avatar';
export { TooltipLayer, useTip } from './primitives/Tooltip';
export type { TipAttributes, TipSide } from './primitives/Tooltip';
export { GlossaryProvider, Term, glossaryEntry, useGlossary } from './primitives/Glossary';
export type { Glossary, GlossaryEntry, GlossaryProviderProps, TermProps } from './primitives/Glossary';
export { When, formatWhen, formatWhenAbsolute } from './primitives/When';
export type { WhenProps } from './primitives/When';
export { HelpLink } from './primitives/HelpLink';
export type { HelpLinkProps } from './primitives/HelpLink';
export { STEP_STATE_LABELS, Stepper } from './primitives/Stepper';
export type { StepItem, StepState, StepperProps } from './primitives/Stepper';
export { Timeline } from './primitives/Timeline';
export type { TimelineEntry, TimelineProps, TimelineTone } from './primitives/Timeline';

// Layout
export {
  SPLIT_DEFAULT_WIDTH,
  SPLIT_MAX_WIDTH,
  SPLIT_MIN_DETAIL,
  SPLIT_MIN_WIDTH,
  SPLIT_STACK_BELOW,
  SplitLayout,
  clampSplitWidth,
} from './layout/SplitLayout';
export type { SplitLayoutProps } from './layout/SplitLayout';

// Overlays
export { Modal, ModalSection } from './overlays/Modal';
export type { ModalAction, ModalCloseReason, ModalProps, ModalSectionProps, ModalSize } from './overlays/Modal';
export { useConfirm, usePrompt } from './overlays/dialogs';
export type { ConfirmApi, ConfirmOptions, PromptApi, PromptOptions } from './overlays/dialogs';
export { RecordChip, RecordPreviewProvider, createRecordRegistry, useRecordPreview } from './overlays/RecordPreview';
export type {
  RecordBodyContext,
  RecordChipProps,
  RecordOpenContext,
  RecordPreviewApi,
  RecordPreviewProviderProps,
  RecordRef,
  RecordRegistry,
  RecordTypeDef,
} from './overlays/RecordPreview';
export { Toaster, useToast } from './overlays/Toaster';
export type { ToastAction, ToastApi, ToastOptions, ToastVariant, ToasterProps } from './overlays/Toaster';
export { Menu, Popover } from './overlays/Popover';
export type { MenuItemDef, MenuProps, Placement, PopoverProps } from './overlays/Popover';
export { InfoTip } from './overlays/InfoTip';
export type { InfoTipProps } from './overlays/InfoTip';

// Required chrome
export { CommandPalette, PALETTE_OPEN_EVENT, SearchTrigger, filterPaletteItems, groupPaletteItems, highlight, isSlashOpen, onPaletteOpen, openCommandPalette, openScopedPalette, paletteOwnsKey, paletteScope, scorePaletteItem } from './chrome/CommandPalette';
export type { CommandPaletteProps, PaletteFilter, PaletteItem, SearchTriggerProps } from './chrome/CommandPalette';
export { BuildCard, ReleaseNotesDialog, RollingText, safeReleaseLink, versionLabel } from './chrome/BuildCard';
export type { BuildCardProps, ReleaseItem, ReleaseItemType, ReleaseNote, ReleaseNotesDialogProps, ReleaseNotesLink } from './chrome/BuildCard';
export { FeedStrip, Presenter } from './chrome/FeedStrip';
export type { FeedItem, FeedStripProps, FeedTone, HealthLine, HealthStatus } from './chrome/FeedStrip';
export {
  AnnouncementBanner,
  AnnouncementStack,
  DISMISSED_CAP,
  addDismissed,
  readDismissed,
  sortAnnouncements,
  useDismissed,
  visibleAnnouncements,
} from './chrome/Announcement';
export type { Announcement, AnnouncementBannerProps, AnnouncementStackProps, AnnouncementTone } from './chrome/Announcement';
export { DEFAULT_MAX_PINS, PinButton, createMemoryPinsStore, isPinned, pageAt, sanitizePins, usePins } from './chrome/PinButton';
export type { DeclaredPage, MemoryPinsStoreOptions, Pin, PinButtonProps, PinsSnapshot, PinsStore } from './chrome/PinButton';
export { ActionsBlock, FeedBlock, HomeItemRow, HubLink, PinnedBlock, ToolChip, homeHref } from './chrome/HomeBlocks';
export type {
  ActionsBlockProps,
  FeedBlockProps,
  HomeAction,
  HomeFeedSource,
  HomeItem,
  HomeItemRowProps,
  HomeTone,
  HomeTool,
  HubLinkProps,
  PinnedBlockProps,
  ToolChipProps,
} from './chrome/HomeBlocks';
export { DEFAULT_HUB_ZONES, HubHome } from './chrome/HubHome';
export type { HubHomeProps, HubZones } from './chrome/HubHome';
export { RECENT_MAX, addRecent, sanitizeRecents } from './chrome/recents';
export type { Recent } from './chrome/recents';
export { AccountMenu, accountDisplayName } from './chrome/AccountMenu';
export type { AccountAction, AccountFact, AccountIdentity, AccountLink, AccountMenuProps } from './chrome/AccountMenu';
export { LAUNCHER_KEYS, LAUNCHER_TIMING, ToolLauncher, ToolSwitchButton, openToYouLabel, slideOffset, useToolLauncher } from './chrome/ToolLauncher';
export type { LauncherTool, ToolLauncherProps, ToolLauncherState, ToolSwitchButtonProps, UseToolLauncherOptions } from './chrome/ToolLauncher';
export { ShortcutLayer } from './chrome/ShortcutLayer';
export type { ShortcutLayerProps } from './chrome/ShortcutLayer';
export { useShortcut } from './lib/shortcuts';
export type { ShortcutDef } from './lib/shortcuts';

// Charts
export {
  categoricalHueNames,
  categoricalPalette,
  chartTheme,
  resolveColor,
  useCategoricalHues,
  useChartTheme,
  watchTheme,
  withheldHue,
} from './charts/chartTheme';
export type { ChartTheme, HueSwatch } from './charts/chartTheme';

// Helpers
export { CATEGORICAL_HUES, EXTRA_HUES, hueFor, initialsOf, isCategoricalHue, isMarkHue, isSeriesHue } from './lib/hues';
export type { CategoricalHue, ExtraHue, MarkHue, NavHue, SeriesHue } from './lib/hues';
export { APP_ID_PATTERN, STORAGE_KEYS, cx, isMacLike, isTypingTarget, onMediaChange, prefersReducedMotion, storageKeys } from './lib/env';
export type { StorageKeys } from './lib/env';
export { StorageScope, useStorageKeys, useStorageScope } from './lib/scope';
export type { StorageScopeProps } from './lib/scope';
export { isDialogOpen, layerRoot, useModalLayer } from './lib/layers';
export { safeHref } from './lib/url';
export type { ModalLayerOptions } from './lib/layers';
export { tokenDuration, tokenValue } from './lib/timing';
export { PHONE_QUERY, SHELL_QUERY, readColorScheme, useColorScheme, useIsPhone, useMediaQuery } from './lib/media';
export type { ColorScheme } from './lib/media';

// Chrome icons
export {
  IconAlert,
  IconArrowLeft,
  IconArrowUp,
  IconCalendar,
  IconCheck,
  IconCheckCircle,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconClock,
  IconClose,
  IconCopy,
  IconEdit,
  IconExternal,
  IconEye,
  IconEyeOff,
  IconFolder,
  IconGrid,
  IconHelp,
  IconHome,
  IconInfo,
  IconList,
  IconLogOut,
  IconMail,
  IconMenu,
  IconMonitor,
  IconMoon,
  IconMore,
  IconPause,
  IconPin,
  IconPinOff,
  IconPlay,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconShield,
  IconSparkle,
  IconSun,
  IconTrash,
  IconWarning,
} from './icons/icons';
export type { IconComponent, IconProps } from './icons/icons';

export { createMemoryTileOrderStore, moveInOrder, placeInOrder, reconcileOrder, useTileReorder } from './hooks/useTileReorder';
export type { Polled, UsePollingOptions } from './hooks/usePolling';
export { usePolling } from './hooks/usePolling';
export type { DropEdge, EndZoneProps, TileEntry, TileOrderStore, TileProps, TileReorder, UseTileReorderOptions } from './hooks/useTileReorder';
export { TileReorderStatus } from './hooks/TileReorderStatus';
export type { TileReorderStatusProps } from './hooks/TileReorderStatus';
// Module contract for a multi-module shell (types only, generated registry and descriptor)
export type {
  ConfigureHost,
  GeneratedRegistry,
  ModuleDescriptor,
  ModuleFeedSource,
  ModuleManifest,
  ModuleRailEntry,
  RegistryEntry,
} from './shell/module';
