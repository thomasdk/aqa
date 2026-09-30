#!/usr/bin/env python3
"""Build or verify the Material Symbols Rounded subset used by AQA.

MaterialSymbol.tsx is the icon-name source of truth. The build keeps exactly
those GSUB ligatures and fails on missing or extra entries. It does not use
``pyftsubset --text`` because that drops the ``rlig`` rules that render icons.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from fontTools.ttLib import TTFont  # type: ignore[import-not-found]

REPO_ROOT = Path(__file__).resolve().parents[1]
TS_FILE = REPO_ROOT / "frontend" / "src" / "components" / "MaterialSymbol.tsx"
OUTPUT_TTF = REPO_ROOT / "frontend" / "src" / "assets" / "fonts" / "MaterialSymbolsRounded-AQA.ttf"

# Google Fonts serves TTF, rather than WOFF, for this legacy user agent.
GFONTS_TTF_UA = "Mozilla/5.0 (X11; U; Linux i686; ru; rv:1.9b5) Gecko/2008050509 Firefox/3.0b5"
GFONTS_CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@24,400,{fill},0"
    "&icon_names={icons}"
)


_TS_ARRAY_RE = re.compile(
    r"MATERIAL_SYMBOL_ICON_NAMES\s*=\s*\[(.*?)\]\s*as\s*const",
    re.DOTALL,
)
_TS_STRING_RE = re.compile(r'"([a-z0-9_]+)"')


def parse_allowed_names(ts_path: Path) -> list[str]:
    """Return icon names in source order from MaterialSymbol.tsx."""
    text = ts_path.read_text(encoding="utf-8")
    match = _TS_ARRAY_RE.search(text)
    if not match:
        raise RuntimeError(f"Could not find MATERIAL_SYMBOL_ICON_NAMES in {ts_path}")
    body = match.group(1)
    names = _TS_STRING_RE.findall(body)
    if not names:
        raise RuntimeError(f"Parsed zero icon names from MATERIAL_SYMBOL_ICON_NAMES in {ts_path}")
    return names


@dataclass(frozen=True)
class LigatureEntry:
    source: str
    target: str


def _ligature_source_text(first_glyph: str, components: Sequence[str], name_to_char: dict) -> str:
    """Reconstruct source text from the first glyph and subsequent components."""
    chars: list[str] = []
    for name in (first_glyph, *components):
        cp = name_to_char.get(name)
        if cp is None:
            chars.append("?")
        else:
            chars.append(chr(cp))
    return "".join(chars)


def collect_ligatures(font: TTFont) -> list[LigatureEntry]:
    """Return all direct or extension-wrapped GSUB ligatures in document order."""
    gsub = font["GSUB"].table
    cmap = font.getBestCmap()  # codepoint -> glyph name
    name_to_char = {gn: cp for cp, gn in cmap.items()}

    out: list[LigatureEntry] = []

    def walk(table_obj) -> None:
        # fontTools exposes nested type-7 extensions through ExtSubTable, but
        # exposes the outer type-7 lookup through its SubTable collection.
        if table_obj.LookupType == 7:
            if hasattr(table_obj, "ExtSubTable") and table_obj.ExtSubTable is not None:
                walk(table_obj.ExtSubTable)
            else:
                for inner in table_obj.SubTable:
                    walk(inner)
            return
        if table_obj.LookupType == 4:  # Ligature
            for first_glyph, names in table_obj.ligatures.items():
                for lig in names:
                    src = _ligature_source_text(first_glyph, lig.Component, name_to_char)
                    out.append(LigatureEntry(source=src, target=lig.LigGlyph))
            return

    for lk in gsub.LookupList.Lookup:
        for st in lk.SubTable:
            walk(st)
    return out


def _filter_ligature_subtable(
    st, allowed: set[str], name_to_char: dict[str, int]
) -> tuple[int, int, list[str]]:
    kept = 0
    dropped = 0
    dropped_sources: list[str] = []
    new_ligatures = {}
    for first_glyph, names in st.ligatures.items():
        retained = []
        for ligature in names:
            source = _ligature_source_text(first_glyph, ligature.Component, name_to_char)
            if source in allowed:
                retained.append(ligature)
                kept += 1
            else:
                dropped += 1
                dropped_sources.append(source)
        if retained:
            new_ligatures[first_glyph] = retained
    st.ligatures = new_ligatures
    return kept, dropped, dropped_sources


def _ligature_subtable(st):
    if st.LookupType == 4:
        return st
    inner = getattr(st, "ExtSubTable", None) if st.LookupType == 7 else None
    return inner if inner is not None and inner.LookupType == 4 else None


def _lookup_subtable_empty(st) -> bool:
    if st.LookupType == 4:
        return not st.ligatures
    if st.LookupType != 7:
        return False
    inner = getattr(st, "ExtSubTable", None)
    return not inner.ligatures if inner is not None else not st.SubTable


def trim_ligatures(font: TTFont, allowed: set[str]) -> tuple[int, int, list[str]]:
    name_to_char = {name: codepoint for codepoint, name in font.getBestCmap().items()}
    kept = 0
    dropped = 0
    dropped_sources: list[str] = []
    for lookup in font["GSUB"].table.LookupList.Lookup:
        for subtable in list(lookup.SubTable):
            ligatures = _ligature_subtable(subtable)
            if ligatures is not None:
                kept_count, dropped_count, sources = _filter_ligature_subtable(
                    ligatures, allowed, name_to_char
                )
                kept += kept_count
                dropped += dropped_count
                dropped_sources.extend(sources)
            if _lookup_subtable_empty(subtable):
                lookup.SubTable.remove(subtable)
    return kept, dropped, dropped_sources


def verify_ligature_parity(
    font: TTFont, allowed: set[str]
) -> tuple[bool, list[str], list[str], list[str]]:
    """Check that the saved TTF matches the allowed icon-name set.

    Returns (ok, missing_in_font, extra_in_font, kept_list). `missing` is
    the subset of `allowed` that has no ligature in the TTF; `extra` is
    the set of ligature sources present in the TTF but not in `allowed`.
    """
    entries = collect_ligatures(font)
    sources = [e.source for e in entries]
    src_set = set(sources)
    missing = sorted(s for s in allowed if s not in src_set)
    extra = sorted(s for s in src_set if s not in allowed)
    return (not missing and not extra), missing, extra, sources


def fetch_upstream_ttf(allowed: Sequence[str], *, fill: int = 0) -> bytes:
    try:
        import requests  # type: ignore[import-not-found]
    except ImportError as e:
        raise RuntimeError(
            "The `requests` package is required to fetch the upstream TTF. "
            "Install it (it is already in requirements.txt) and try again."
        ) from e

    icons_csv = ",".join(allowed)
    css_url = GFONTS_CSS_URL.format(icons=icons_csv, fill=fill)

    css_resp = requests.get(css_url, headers={"User-Agent": GFONTS_TTF_UA}, timeout=30)
    css_resp.raise_for_status()
    css = css_resp.text

    src_match = re.search(r"src:\s*url\((https?://[^)]+)\)", css)
    if not src_match:
        raise RuntimeError(f"Could not parse font URL from GFonts CSS response:\n{css}")
    font_url = src_match.group(1)

    bin_resp = requests.get(font_url, headers={"User-Agent": GFONTS_TTF_UA}, timeout=30)
    bin_resp.raise_for_status()
    return bin_resp.content


def cmd_build(args: argparse.Namespace) -> int:
    allowed_list = parse_allowed_names(TS_FILE)
    allowed = set(allowed_list)
    print(f"Allowed icon names: {len(allowed_list)} (from {TS_FILE.relative_to(REPO_ROOT)})")
    print(f"Sample: {allowed_list[:5]}... {allowed_list[-3:]}")

    if not args.no_fetch:
        print("Fetching upstream TTF from Google Fonts CSS API...")
        ttf_bytes = fetch_upstream_ttf(allowed_list, fill=args.fill)
        print(f"  Downloaded {len(ttf_bytes):,} bytes")
    else:
        ttf_path = Path(args.no_fetch)
        ttf_bytes = ttf_path.read_bytes()
        print(f"Using upstream TTF from {ttf_path}: {len(ttf_bytes):,} bytes")

    font = TTFont(io.BytesIO(ttf_bytes))
    n_tables_before = len(font.keys())
    n_glyphs_before = font["maxp"].numGlyphs
    n_ligs_before = len(collect_ligatures(font))
    print(
        f"  Pre-trim: {n_tables_before} tables, {n_glyphs_before} glyphs, "
        f"{n_ligs_before} GSUB ligatures"
    )

    kept, dropped, dropped_sources = trim_ligatures(font, allowed)
    print(f"  Trimmed: kept {kept}, dropped {dropped} ligatures")
    if dropped:
        print(f"  Dropped sources (first 20): {dropped_sources[:20]}")

    ok, missing, extra, _kept_list = verify_ligature_parity(font, allowed)
    if not ok:
        print("PARITY FAILURE after trim:", file=sys.stderr)
        if missing:
            print(f"  Missing from font: {missing}", file=sys.stderr)
        if extra:
            print(f"  Extra in font: {extra}", file=sys.stderr)
        return 1
    print(f"  Parity: {kept} ligatures == {len(allowed)} allowed names ✓")

    # Preserve upstream identity and attribution metadata in the subset.
    name_table = font["name"]
    family = None
    copyright_str = None
    for rec in name_table.names:
        if rec.nameID == 1 and family is None:
            try:
                family = rec.toUnicode()
            except Exception:
                family = None
        if rec.nameID == 0 and copyright_str is None:
            try:
                copyright_str = rec.toUnicode()
            except Exception:
                copyright_str = None
    print(f"  name[1] (family): {family!r}")
    print(f"  name[0] (copyright): {copyright_str!r}")
    if family != "Material Symbols Rounded":
        print(
            f"WARN: family name is {family!r}, expected 'Material Symbols Rounded'", file=sys.stderr
        )

    output_ttf = Path(args.output).resolve() if args.output else OUTPUT_TTF
    output_ttf.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(output_ttf))
    size = output_ttf.stat().st_size
    sha = hashlib.sha256(output_ttf.read_bytes()).hexdigest()
    print(f"\nWrote {output_ttf.relative_to(REPO_ROOT)}: {size:,} bytes")
    print(f"SHA-256: {sha}")
    print(
        f"Post-trim: {len(font.keys())} tables, "
        f"{font['maxp'].numGlyphs} glyphs, {kept} GSUB ligatures"
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    allowed_list = parse_allowed_names(TS_FILE)
    allowed = set(allowed_list)
    print(f"Allowed icon names: {len(allowed_list)} (from {TS_FILE.relative_to(REPO_ROOT)})")

    ttf_path = Path(args.ttf).resolve() if args.ttf else OUTPUT_TTF
    if not ttf_path.exists():
        print(f"ERROR: TTF not found: {ttf_path}", file=sys.stderr)
        return 1
    print(f"Verifying {ttf_path.relative_to(REPO_ROOT)} ({ttf_path.stat().st_size:,} bytes)")

    font = TTFont(str(ttf_path))
    n_tables = len(font.keys())
    n_glyphs = font["maxp"].numGlyphs

    ok, missing, extra, kept = verify_ligature_parity(font, allowed)
    print(f"Tables: {n_tables}, glyphs: {n_glyphs}, GSUB ligatures: {len(kept)}")

    if not ok:
        print("PARITY FAILURE:", file=sys.stderr)
        if missing:
            print(f"  Missing from font: {missing}", file=sys.stderr)
        if extra:
            print(f"  Extra ligatures in font: {extra}", file=sys.stderr)
        return 1
    if len(kept) != len(allowed):
        print(f"PARITY FAILURE: {len(kept)} ligatures != {len(allowed)} allowed", file=sys.stderr)
        return 1
    print(f"Parity: {len(kept)} ligatures == {len(allowed)} allowed names ✓")
    print(f"Kept ligatures: {sorted(set(kept))}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser(
        "build", help="Fetch upstream TTF, trim GSUB, write to AQA asset path."
    )
    p_build.add_argument(
        "--no-fetch",
        metavar="PATH",
        help="Skip the network fetch; read the upstream TTF from PATH.",
    )
    p_build.add_argument(
        "--fill",
        type=int,
        choices=(0, 1),
        default=0,
        help="Static Material Symbols FILL axis value to fetch (default: 0).",
    )
    p_build.add_argument(
        "--output",
        help="Output TTF path (default: the standard outline AQA asset).",
    )
    p_build.set_defaults(func=cmd_build)

    p_verify = sub.add_parser(
        "verify",
        help="Verify an existing TTF against the icon-name union (defaults to the AQA asset path).",
    )
    p_verify.add_argument("--ttf", help="Path to TTF (default: the AQA asset).")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
