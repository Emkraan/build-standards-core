export type ScopeRootMode = 'wrapper' | 'document';
export type ScopeKeyframesMode = 'warn' | 'strict' | 'rename';
export function scopeOf(id: string): string;
export function scopeSelector(selector: string, id: string, options?: { root?: ScopeRootMode }): string;
export interface ScopeModuleCssOptions {
  /** Same as keyframes: 'strict'. */
  strictKeyframes?: boolean;
  /** What to do with a keyframes name that lacks the "<id>-" prefix. Default 'warn'. */
  keyframes?: ScopeKeyframesMode;
  /** Where :root, html, body and #root land. Default 'wrapper'. */
  root?: ScopeRootMode;
}
export interface ScopePlugin {
  postcssPlugin: string;
  Once(root: unknown, helpers: { result: { warn(text: string, opts?: unknown): void } }): void;
}
export function scopeModuleCss(files: Record<string, string>, options?: ScopeModuleCssOptions): ScopePlugin;
