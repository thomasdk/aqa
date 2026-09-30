import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import AqaBrand from "./AqaBrand";

describe("AqaBrand", () => {
  it("renders a non-interactive div composition", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html.startsWith("<div")).toBe(true);
  });

  it("becomes a named button when a preparation shortcut is supplied", () => {
    const html = renderToStaticMarkup(<AqaBrand onActivate={() => undefined} />);
    expect(html.startsWith("<button")).toBe(true);
    expect(html).toMatch(/aria-labelledby="aqa-brand-label"/);
  });

  it("keeps the root accessible-name contract: aria-labelledby -> aqa-brand-label, no aria-label duplication", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html).toMatch(/aria-labelledby="aqa-brand-label"/);
    expect(html).not.toMatch(/aria-label="AQA"/);
  });

  it("renders a visually-hidden label span with id aqa-brand-label containing 'AQA'", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html).toMatch(/<span[^>]*id="aqa-brand-label"[^>]*>AQA<\/span>/);
    expect(html).toMatch(/<span[^>]*id="aqa-brand-label"[^>]*class="[^"]*visually-hidden[^"]*"/);
  });

  it("retains data-aqa-brand='true' on the root element", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html).toMatch(/data-aqa-brand="true"/);
  });

  it("renders three decorative wordmark letters in the AQA wave order", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    const letters = Array.from(
      html.matchAll(
        /<span[^>]*class="[^"]*\baqa-brand-letter\b[^"]*"[^>]*data-aqa-wave="([1-7])"[^>]*>([AQA])<\/span>/g,
      ),
    );

    expect(letters.map((match) => match[2])).toEqual(["A", "Q", "A"]);
    expect(letters.map((match) => match[1])).toEqual(["3", "4", "5"]);
    for (const letter of letters) {
      expect(letter[0]).toContain('aria-hidden="true"');
    }
  });

  it("marks the complete seven-part wave as idle by default and generating on request", () => {
    const idle = renderToStaticMarkup(<AqaBrand />);
    const generating = renderToStaticMarkup(<AqaBrand isGenerating />);

    expect(idle).toContain('data-aqa-generating="false"');
    expect(generating).toContain('data-aqa-generating="true"');
    for (const html of [idle, generating]) {
      const waveParticipants = html.match(/data-aqa-wave="[1-7]"/g) ?? [];
      expect(waveParticipants).toHaveLength(7);
    }
  });

  it("keeps the same seven wave participants when generation ends", () => {
    const active = renderToStaticMarkup(<AqaBrand isGenerating />);
    const idle = renderToStaticMarkup(<AqaBrand isGenerating={false} />);

    expect(active.match(/data-aqa-wave="[1-7]"/g)).toHaveLength(7);
    expect(idle.match(/data-aqa-wave="[1-7]"/g)).toHaveLength(7);
    expect(active).toContain('data-aqa-generating="true"');
    expect(idle).toContain('data-aqa-generating="false"');
  });

  it("preserves every participant and changes playback rate without restarting its timeline", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const animations = new WeakMap<
      Element,
      { animationName: string; updatePlaybackRate: ReturnType<typeof vi.fn> }
    >();
    const getAnimations = vi.fn(function (this: Element) {
      if (!this.hasAttribute("data-aqa-wave")) return [];
      let animation = animations.get(this);
      if (!animation) {
        animation = { animationName: "aqa-brand-wave", updatePlaybackRate: vi.fn() };
        animations.set(this, animation);
      }
      return [animation as unknown as Animation];
    });
    Object.defineProperty(Element.prototype, "getAnimations", {
      configurable: true,
      value: getAnimations,
    });

    act(() => root.render(<AqaBrand isGenerating={false} />));
    const brand = container.querySelector<HTMLElement>("[data-aqa-brand]")!;
    const participants = Array.from(brand.querySelectorAll<HTMLElement>("[data-aqa-wave]"));
    expect(participants).toHaveLength(7);
    participants.forEach((participant) => {
      expect(animations.get(participant)?.updatePlaybackRate).toHaveBeenLastCalledWith(1);
    });

    act(() => root.render(<AqaBrand isGenerating />));
    expect(container.querySelector("[data-aqa-brand]")).toBe(brand);
    expect(Array.from(brand.querySelectorAll("[data-aqa-wave]"))).toEqual(participants);
    participants.forEach((participant) => {
      expect(animations.get(participant)?.updatePlaybackRate).toHaveBeenLastCalledWith(4.875);
    });

    act(() => root.render(<AqaBrand isGenerating={false} />));
    expect(container.querySelector("[data-aqa-brand]")).toBe(brand);
    expect(Array.from(brand.querySelectorAll("[data-aqa-wave]"))).toEqual(participants);
    participants.forEach((participant) => {
      const update = animations.get(participant)?.updatePlaybackRate;
      expect(update).toHaveBeenLastCalledWith(1);
      expect(update).toHaveBeenCalledTimes(3);
    });

    act(() => root.unmount());
    container.remove();
    delete (Element.prototype as Partial<Element>).getAnimations;
  });

  it("renders the exact subtitle in German", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html).toContain("Augmented Qualitative Analysis");
  });

  it("renders exactly four decorative drops", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    const dropNodes = html.match(/<svg[^>]*data-aqa-drop="[^"]+"[^>]*>/g) ?? [];
    expect(dropNodes).toHaveLength(4);
  });

  it("renders exactly two left drops and two right drops with the required fill sequence", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    const drops = Array.from(html.matchAll(/<svg[^>]*data-aqa-drop="([^"]+)"[^>]*>/g));
    expect(drops).toHaveLength(4);

    const slots = drops.map((m) => m[1]);
    expect(slots).toEqual(["left-outline", "left-half", "right-half", "right-full"]);
  });

  it("tags every drop with data-aqa-side left/right and data-aqa-fill outline/half/full", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    for (const expected of ["left-outline", "left-half", "right-half", "right-full"]) {
      const tag = new RegExp(
        `<svg[^>]*data-aqa-drop="${expected}"[^>]*data-aqa-side="(left|right)"[^>]*data-aqa-fill="(outline|half|full)"[^>]*>`,
      );
      expect(html).toMatch(tag);
    }
  });

  it("marks every drop SVG decorative (aria-hidden='true' and focusable='false')", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    const dropSvgs = html.match(/<svg[^>]*data-aqa-drop="[^"]+"[^>]*>[\s\S]*?<\/svg>/g) ?? [];
    expect(dropSvgs).toHaveLength(4);
    for (const svg of dropSvgs) {
      expect(svg).toMatch(/aria-hidden="true"/);
      expect(svg).toMatch(/focusable="false"/);
    }
  });

  it("does not import MaterialSymbol for the drops (no water_drop ligature marks)", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    expect(html).not.toMatch(/>water_drop<\/span>/);
    const iconSpans = html.match(/<span[^>]*class="[^"]*material-symbol[^"]*"[^>]*>/g) ?? [];
    expect(iconSpans).toHaveLength(0);
  });

  it("wraps the two left drops in one .aqa-brand-lockup group and the two right drops in another, both before the tagline", () => {
    const html = renderToStaticMarkup(<AqaBrand />);

    const groups = Array.from(
      html.matchAll(/<div[^>]*class="[^"]*\baqa-brand-lockup\b[^"]*"[^>]*>([\s\S]*?)<\/div>/g),
    );
    expect(groups).toHaveLength(2);

    const slotSequences = groups.map((g) => {
      const inner = g[1];
      const slots = Array.from(inner.matchAll(/data-aqa-drop="([^"]+)"/g)).map((m) => m[1]);
      return slots;
    });

    expect(slotSequences[0]).toEqual(["left-outline", "left-half"]);
    expect(slotSequences[1]).toEqual(["right-half", "right-full"]);
  });

  it("shifts every drop <path> by translate(0 960) so the source y range (-860..-100) maps inside the 0..960 viewBox", () => {
    const html = renderToStaticMarkup(<AqaBrand />);
    const dropPathTags = html.match(/<svg[^>]*data-aqa-drop="[^"]+"[^>]*>[\s\S]*?<\/svg>/g) ?? [];
    expect(dropPathTags).toHaveLength(4);
    for (const svg of dropPathTags) {
      const pathMatch = svg.match(/<path\s[^>]*?><\/path>/) ?? svg.match(/<path\s[^>]*\/>/);
      expect(pathMatch).not.toBeNull();
      const pathTag = pathMatch![0];
      const transformMatch = pathTag.match(/transform="([^"]*)"/);
      expect(transformMatch).not.toBeNull();
      const transformValue = transformMatch![1].trim();
      expect(transformValue).toBe("translate(0 960)");
    }
  });

  it("orders the DOM as: brand root -> left lockup -> wordmark -> right lockup -> tagline", () => {
    const html = renderToStaticMarkup(<AqaBrand />);

    const idxLeft = html.search(/class="[^"]*\baqa-brand-lockup\b[^"]*"/);
    const idxWordmark = html.search(/class="[^"]*\baqa-brand-wordmark\b[^"]*"/);
    const idxRight = html.lastIndexOf('class="aqa-brand-lockup');
    const idxTagline = html.search(/class="[^"]*\baqa-brand-tagline\b[^"]*"/);

    expect(idxLeft).toBeGreaterThan(-1);
    expect(idxWordmark).toBeGreaterThan(idxLeft);
    expect(idxRight).toBeGreaterThan(idxWordmark);
    expect(idxTagline).toBeGreaterThan(idxRight);
  });
});
