// Applies the consumer preset the app-server tests run under, then exports what is in force.
//
// By default the tests run on the core names (an empty preset call). With TEST_CONSUMER_PRESET set
// to a JSON file path, or to inline JSON, the whole suite runs under that preset instead, which is
// how a consumer's naming is proven not to change behaviour. Every test reads the names it needs
// from P (never from a literal), so the same assertions hold under either run.
import { readFileSync } from "node:fs";
import { setConsumerPreset, getConsumerPreset } from "../../../shell-packages/app-server/index.js";

/** @returns {Record<string, any>} */
function load() {
  const raw = (process.env.TEST_CONSUMER_PRESET || "").trim();
  if (!raw) return {};
  return JSON.parse(raw.startsWith("{") ? raw : readFileSync(raw, "utf8"));
}

setConsumerPreset(load());

/** The preset the suite runs under. */
export const P = getConsumerPreset();

/** Put the suite's preset back (a test that changed or reset it calls this in finally). */
export function restorePreset() {
  setConsumerPreset(P);
}
