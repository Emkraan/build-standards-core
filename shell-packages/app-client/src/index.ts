/* shell-packages/app-client: the shared browser client for multi-module shell apps. One sign-in boot, one
   API client with a shared cache, the useResource hook and the console feed strip. */

export { RETURN_TO_KEY, createAuth, isShellMode } from './auth';
export type { Auth, AuthError, AuthMode, AuthOptions, BootResult, TokenOptions } from './auth';
export { safeReturnTo } from './returnTo';
export { createApi, qs } from './api';
export type { Api, ApiDetails, ApiError, CreateApiOptions, GetOptions, QueryParams, RequestOptions } from './api';
export { createStore, defaultStore, isStale } from './cache';
export type { FetchOptions, ResourceSnapshot, ResourceStore, StaleError } from './cache';
export { useApiResource, useResource } from './useResource';
export type { UseResourceOptions, UseResourceResult } from './useResource';
export {
  ConsoleFeed,
  FEED_FRESH_MS,
  FEED_MAX_ITEMS,
  FEED_SIDE_KEY,
  FEED_POLL_MS,
  healthStatusOf,
  mergeHealth,
  mergeItems,
  parseFeed,
  useConsoleFeed,
} from './feed';
export type { ConsoleFeedProps, ConsoleFeedState, FeedEntry, PlatformFeed, UseConsoleFeedOptions } from './feed';
