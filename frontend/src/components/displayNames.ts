import type { TFunction } from "i18next";
import type { HostInfo } from "./types";

const KNOWN_GEMMA_MODELS: Record<string, string> = {
  "gemma-4-e2b": "Gemma 4 E2B",
  "gemma-4-e2b-it": "Gemma 4 E2B",
  "gemma-4-e4b": "Gemma 4 E4B",
  "gemma-4-e4b-it": "Gemma 4 E4B",
  "gemma-4-12b": "Gemma 4 12B",
  "gemma-4-12b-it": "Gemma 4 12B",
};

/** Render managed technical values for people without changing stored values. */
export function displayModelName(value: string | null | undefined): string {
  const model = value?.trim() ?? "";
  return KNOWN_GEMMA_MODELS[model.toLowerCase()] ?? model;
}

/** Managed host labels are UI chrome; user-defined host labels stay verbatim. */
export function displayHostLabel(host: Pick<HostInfo, "kind" | "label">, t: TFunction): string {
  return host.kind === "local_ai" ? t("nav.localAi") : host.label;
}
