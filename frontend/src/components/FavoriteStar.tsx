import MaterialSymbol from "./MaterialSymbol";

type FavoriteStarProps = {
  isFavorite: boolean;
};

/**
 * Decorative shared favorite marker. Interactive owners provide the label,
 * title, and pressed state; this component only standardizes the glyph and
 * visual state across host and session surfaces.
 */
export const FavoriteStar = ({ isFavorite }: FavoriteStarProps) => (
  <span className={`favorite-star ${isFavorite ? "is-active" : "is-inactive"}`} aria-hidden="true">
    <MaterialSymbol name={isFavorite ? "star" : "star_border"} decorative />
  </span>
);
