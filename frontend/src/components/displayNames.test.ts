import { describe, expect, it } from "vitest";
import type { TFunction } from "i18next";
import { displayHostLabel, displayModelName } from "./displayNames";

const translate = ((key: string) => (key === "nav.localAi" ? "Integrated AI" : key)) as TFunction;

describe("display names", () => {
  it("formats known Gemma IDs and aliases without changing unknown models", () => {
    expect(displayModelName("gemma-4-e2b")).toBe("Gemma 4 E2B");
    expect(displayModelName("gemma-4-E4B-it")).toBe("Gemma 4 E4B");
    expect(displayModelName("gemma-4-12B-it")).toBe("Gemma 4 12B");
    expect(displayModelName("gpt-4.1")).toBe("gpt-4.1");
  });

  it("localizes the managed host while preserving external labels", () => {
    expect(displayHostLabel({ kind: "local_ai", label: "Integrierte KI" }, translate)).toBe(
      "Integrated AI",
    );
    expect(displayHostLabel({ kind: "openai", label: "Research Cluster" }, translate)).toBe(
      "Research Cluster",
    );
  });
});
