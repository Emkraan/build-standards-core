export interface VisualUpdateSettings {
  mode: '--ci' | '--docker' | '--local';
  root: string;
  baselines: string;
  build: string | null;
  workflow: string;
  artifact: string;
}
export function parseArgs(argv: string[]): VisualUpdateSettings;
export function dockerArgs(settings: VisualUpdateSettings, env: { version: string; repoDir: string }): string[];
