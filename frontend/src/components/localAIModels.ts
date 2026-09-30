import type { LocalAIModelCatalogEntry, LocalAIModelId } from "../api";

export const LOCAL_AI_MODEL_CATALOG: Record<LocalAIModelId, LocalAIModelCatalogEntry> = {
  "gemma-4-e2b": {
    id: "gemma-4-e2b",
    label: "Gemma 4 E2B",
    description: "",
    memory: "",
    model_size: "2,62 GB",
    draft_size: "ca. 59 MB",
    model_url: "https://huggingface.co/unsloth/gemma-4-E2B-it-qat-GGUF",
    model_bytes: 2_620_368_960,
    draft_bytes: 59_234_176,
  },
  "gemma-4-e4b": {
    id: "gemma-4-e4b",
    label: "Gemma 4 E4B",
    description: "",
    memory: "",
    model_size: "4,22 GB",
    draft_size: "ca. 60 MB",
    model_url: "https://huggingface.co/unsloth/gemma-4-E4B-it-qat-GGUF",
    model_bytes: 4_215_693_760,
    draft_bytes: 59_676_544,
  },
  "gemma-4-12b": {
    id: "gemma-4-12b",
    label: "Gemma 4 12B",
    description: "",
    memory: "",
    model_size: "6.72 GB",
    draft_size: "ca. 254 MB",
    model_url: "https://huggingface.co/unsloth/gemma-4-12B-it-qat-GGUF",
    model_bytes: 6_720_000_000,
    draft_bytes: 254_000_000,
  },
};

export const LOCAL_AI_MODEL_ORDER: LocalAIModelId[] = ["gemma-4-e2b", "gemma-4-e4b", "gemma-4-12b"];

// Keep these documented model capabilities aligned with src/local_ai/catalog.py.
export const LOCAL_AI_MODEL_MAX_CONTEXT: Record<LocalAIModelId, number> = {
  "gemma-4-e2b": 131_072,
  "gemma-4-e4b": 131_072,
  "gemma-4-12b": 262_144,
};
