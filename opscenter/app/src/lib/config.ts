// Build time parameters of the app (local/params.json, passed to the build as VITE_ variables).
// A value that is not set falls back to a neutral default, never to an estate name.
export const PRIMARY_REPO: string = import.meta.env.VITE_PRIMARY_REPO ?? 'owner/primary'
export const APP_SUBTITLE: string = import.meta.env.VITE_APP_SUBTITLE ?? ''
export const prUrl = (n: number | string | null): string => `https://github.com/${PRIMARY_REPO}/pull/${n}`
