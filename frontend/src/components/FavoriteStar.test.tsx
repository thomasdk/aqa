import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { FavoriteStar } from "./FavoriteStar";

describe("FavoriteStar", () => {
  it("renders the 'star' ligature inside a favorite-star wrapper when active", () => {
    const html = renderToStaticMarkup(<FavoriteStar isFavorite />);
    expect(html).toMatch(/<span[^>]*class="[^"]*\bfavorite-star\b[^"]*"/);
    expect(html).toMatch(/<span[^>]*class="[^"]*\bfavorite-star\b[^"]*\bis-active\b[^"]*"/);
    expect(html).toMatch(/<span[^>]*class="material-symbol"[^>]*>star<\/span>/);
    expect(html).not.toMatch(/role="img"/);
  });

  it("renders the 'star_border' ligature inside a favorite-star wrapper when inactive", () => {
    const html = renderToStaticMarkup(<FavoriteStar isFavorite={false} />);
    expect(html).toMatch(/<span[^>]*class="[^"]*\bfavorite-star\b[^"]*"/);
    expect(html).toMatch(/<span[^>]*class="[^"]*\bfavorite-star\b[^"]*\bis-inactive\b[^"]*"/);
    expect(html).not.toMatch(/\bis-active\b/);
    expect(html).toMatch(/<span[^>]*class="material-symbol"[^>]*>star_border<\/span>/);
  });

  it("exposes no accessible label — caller owns the label/interactivity", () => {
    const html = renderToStaticMarkup(<FavoriteStar isFavorite />);
    expect(html).not.toMatch(/aria-label=/);
    expect(html).not.toMatch(/role="img"/);
    expect(html).toMatch(/aria-hidden="true"/);
  });
});
