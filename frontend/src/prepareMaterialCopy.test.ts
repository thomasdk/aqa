import { describe, expect, it } from "vitest";
import { de, en } from "./locales";

describe("Prepare material segment copy", () => {
  it("names the segment workflow and warns against using the full text", () => {
    expect(en.setup.addMaterial).toBe("Add Material Segment");
    expect(en.setup.addMaterialDescription).toBe(
      "This workflow is designed for one especially dense segment of the material, not the full text. With lengthy material, the app may stop functioning.",
    );
    expect(de.setup.addMaterial).toBe("Materialsegment hinzufügen");
    expect(de.setup.addMaterialDescription).toBe(
      "Dieser Ablauf ist für ein besonders dichtes Materialsegment gedacht, nicht für den vollständigen Text. Bei langen Materialien funktioniert die App möglicherweise nicht mehr.",
    );
  });

  it("keeps normal and excessive-input guidance concise in both locales", () => {
    expect(en.setup.integratedMaterialDurationGuidance).toBe(
      "Longer material takes longer to process. The first answer may take several minutes.",
    );
    expect(de.setup.integratedMaterialDurationGuidance).toBe(
      "Längeres Material braucht länger zur Verarbeitung. Die erste Antwort kann mehrere Minuten dauern.",
    );
    expect(en.setup.contextBudgetOverflow).toBe("Input is too long. Shorten the material or task.");
    expect(de.setup.contextBudgetOverflow).toBe(
      "Die Eingabe ist zu lang. Kürze das Material oder den Auftrag.",
    );
  });

  it("uses consistent model-size terminology without weight metaphors", () => {
    expect(en.localAi.modelE2bDescription).toBe(
      "The smallest option, with the lowest memory requirements. Start here.",
    );
    expect(en.localAi.modelE4bDescription).toBe(
      "The medium-sized option. May improve answers, but needs more memory and may respond more slowly.",
    );
    expect(en.localAi.model12bDescription).toBe(
      "The largest option. Try it if E4B runs comfortably and you want to explore potential answer improvements.",
    );
    expect(en.localAi.e4bInvitation).toBe(
      "You can try E4B on this system. It needs more memory and may respond more slowly.",
    );
    expect(de.localAi.modelE2bDescription).toBe(
      "Die kleinste Option mit dem geringsten Speicherbedarf. Beginne hier.",
    );
    expect(de.localAi.modelE4bDescription).toBe(
      "Die mittelgroße Option. Kann Antworten verbessern, benötigt aber mehr Speicher und antwortet möglicherweise langsamer.",
    );
    expect(de.localAi.model12bDescription).toBe(
      "Die größte Option. Probiere sie aus, wenn E4B komfortabel läuft und du mögliche Verbesserungen der Antworten erkunden möchtest.",
    );
    expect(de.localAi.e4bInvitation).toBe(
      "Du kannst E4B auf diesem System ausprobieren. Es benötigt mehr Speicher und antwortet möglicherweise langsamer.",
    );
    for (const copy of [en.localAi, de.localAi]) {
      expect(
        [copy.modelE2bDescription, copy.modelE4bDescription, copy.model12bDescription].join(" "),
      ).not.toMatch(/lightest|heavyweight|leichteste|schwergewichtig/i);
    }
  });
});
