# Plan: Cross-Platform Matching + SoundCloud Collector

## Goal

Make the graph truly multi-platform: tracks and artists from SoundCloud and Deezer
(and any future collector) merge into unified canonical entities. The co-occurrence
graph operates on canonical entities only — platform is just metadata.

## Implementation Order

### Phase 1: Name Normalizer + Title Parser

**Files**: `src/music_graph/matching/normalize.py`, `src/music_graph/matching/title_parser.py`

**normalize.py** — Deterministic name normalization for artists and track titles:
- lowercase, strip whitespace
- Collapse multiple spaces/dashes
- Remove diacritics (unicodedata.normalize NFKD)
- Strip noise tokens: "official", "music", "vevo", "(official audio)", etc.
- For artists: normalize "dj" prefix consistently, strip "the " prefix
- Output: a stable normalized string for exact comparison

**title_parser.py** — Extract artist + track name from SoundCloud-style compound titles:
- Strip known prefixes: `Premiere:`, `PREMIERE -`, `Free DL |`, `FREE DOWNLOAD`
- Strip known suffixes/brackets: `[FREE DL]`, `(OUT NOW)`, `[Label Name]`, `(Original Mix)`
- Split on first separator: ` - `, ` – `, ` — `, ` | `
  - Left = artist(s), Right = track title
- Parse collaboration separators in artist part: ` x `, ` & `, ` feat. `, ` ft. `, ` b2b `
  - Returns list of individual artist names
- Fallback: if no separator found, use uploader name as artist and full title as track name

### Phase 2: SoundCloud Collector

**Files**: `src/music_graph/collectors/soundcloud.py`

Implements `AbstractCollector` protocol using the unofficial v2 API (already researched in `docs/research/collectors_roadmap.md`).

- Auth: `SOUNDCLOUD_OAUTH_TOKEN` + `SOUNDCLOUD_CLIENT_ID` from `.env`
- Rate limiter: 2 req/s, burst 5
- `get_user_playlists(user_id)` -> all playlists (public + private)
- `get_playlist_tracks(playlist_id)` -> full track list (batch-fetch incomplete tracks via `/tracks?ids=`)
- Maps to `RawTrack` / `RawPlaylist` / `RawArtist`:
  - Uses title_parser to extract real artist from track title
  - Falls back to uploader name if parser can't split
  - `duration_ms` from SC API (useful for track matching)
  - `platform_id` = SC numeric track ID

**CLI**: `music-graph sc-collect --user-id 296527166 --max-minutes 15`

### Phase 3: Cross-Platform Match Resolver

**Files**: `src/music_graph/matching/resolver.py`

Post-ingest matching pass that finds cross-platform duplicates and merges them.

**Artist matching**:
1. For each SoundCloud ArtistSource, normalize the name
2. Find Deezer ArtistSource records with same normalized name -> exact match (confidence=1.0)
3. For unmatched: use `rapidfuzz.fuzz.token_sort_ratio` against all Deezer artist names
   - >= 90: auto-accept (confidence=0.9+)
   - 75-89: store as PENDING in match_candidate for manual review
   - < 75: skip
4. Accepted matches: merge by pointing both ArtistSource records to the same canonical Artist
   - Keep the one with more data (more playlist appearances) as canonical
   - Update all TrackArtist references

**Track matching**:
1. For each unmatched SoundCloud TrackSource, normalize (artist + title)
2. Query Deezer TrackSource records by same canonical artist (already matched in step above)
3. Compare: `token_sort_ratio(normalized_title_a, normalized_title_b)`
   - If >= 85 AND duration difference < 5000ms: auto-accept
   - If >= 85 but no duration: store as PENDING
   - If >= 75 AND duration < 3000ms: auto-accept (duration confidence compensates)
4. Accepted matches: merge TrackSource records under one canonical Track
   - Preserve ISRC from whichever source has it
   - Update all PlaylistTrack references

**CLI**: `music-graph match --max-minutes 15` (batch-resumable, uses match_candidate table)

### Phase 4: Pipeline Integration

- After any `sc-collect` batch, auto-run match resolver for newly ingested entities
- After any `expand` batch (Deezer), auto-run match resolver for newly ingested entities
- The `build-graph` command already uses canonical entities — it automatically benefits from merged data
- Add `--include-platforms` filter to `build-graph` for debugging (default: all platforms)

### Phase 5: Verification

- `music-graph stats` shows per-platform breakdown:
  ```
  Artists: 15,717 canonical (14,289 Deezer sources, 175 SoundCloud sources, 142 cross-platform matches)
  Tracks:  57,849 canonical (57,849 Deezer sources, 1,488 SoundCloud sources, ~200 cross-platform matches)
  ```
- `music-graph match-stats` shows matching quality:
  ```
  Artist matches: 120 accepted, 22 pending, 8 rejected
  Track matches: 180 accepted, 45 pending, 12 rejected
  ```
- Build both track graph and artist graph, verify that cross-platform edges exist

## Matching Quality Expectations

For this specific dataset (underground bounce/donk/trance):
- **Artist exact match rate**: ~60-70% (many SC artists also on Deezer with same name)
- **Artist fuzzy match rate**: +10-15% (covers DJ prefix variations, minor spelling differences)
- **Track match rate**: ~20-30% (many SC tracks are unreleased/exclusive, won't be on Deezer)
- **The unmatched SC tracks still add value**: they create SC-only playlist co-occurrence edges in the graph

## Key Design Principles

1. **Never lose platform-specific data** — Source tables preserve everything, merging only affects canonical pointers
2. **Matching is non-destructive** — can always undo by changing match_candidate status back to REJECTED
3. **Batch-resumable** — all steps respect max_minutes, persist progress incrementally
4. **Conservative auto-accept** — high thresholds for auto-merge, lower matches go to review
