# Collection Log

Record of all data collection runs. Update this file after every collection.

## Current DB State

- **Playlists**: 188 Deezer + 808 SoundCloud = 996 total
- **Tracks**: 72,416 canonical (63,702 Deezer sources + 8,714 SoundCloud sources)
- **Artists**: 21,129 canonical (17,292 Deezer sources + 5,073 SoundCloud sources)
- **Genres**: 0 (enrichment not yet run)
- **ISRCs**: 0 (enrichment not yet run)
- **Cross-platform matches**: 161 accepted (65 exact + 96 fuzzy, artists only), 3,254 pending
- **Last updated**: 2026-03-06

## Completed Collections

### 1. Seed Collection (Deezer + SoundCloud overlap)

- **Date**: 2026-03-05
- **Platform**: Deezer (public API)
- **Method**: Playlist search by genre keywords, filtered by overlap with known SoundCloud artists
- **Input**: 175 seed artists from `data/soundcloud_artists.json` (manually extracted from personal SoundCloud playlists — file later overwritten, now contains 6)
- **Keywords**: bouncy techno, bouncy trance, bouncy house, hard bounce, uk bounce, donk, bouncy, euro trance, hard house, acid techno bounce, funky techno, bouncy psy, nrg bounce, latin core, trancecore, hardstyle bounce, neo trance
- **Quality filter**: Playlist only ingested if >= 2 tracks from known artists
- **Result**: 134 playlists at depth=0
- **CLI**: `music-graph seed-collect`

### 2. Expand (Deezer — related artists)

- **Date**: 2026-03-05
- **Platform**: Deezer (public API)
- **Method**: BFS expansion — takes "hub" artists (>= 4 playlists), fetches related artists from Deezer, searches their playlists, ingests those with overlap
- **Pipeline**: discover → search playlists → probe overlap → ingest (batch-resumable with staging in `expand_candidate`)
- **Result**: 54 playlists at depth=1. `expand_candidate` table is now empty (candidates purged after ingestion or staging did not persist)
- **CLI**: `music-graph expand`

### 3. SoundCloud — User playlist collection

- **Date**: 2026-03-05
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Download all playlists (public and private) from a specific user by user_id
- **Auth**: oauth_token + client_id (from browser cookies/scripts)
- **Title parser**: Extracts real artist name from track title (separators: -, –, etc.)
- **Result**: Part of the 787 SC playlists (visible by owner: Throne Room Records 55, COUP 30, Sopranos Bounce 27, etc.)
- **CLI**: `music-graph sc-collect --user-id <id>`

### 4. SoundCloud — Keyword search

- **Date**: 2026-03-05
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Playlist search by genre keywords
- **Keywords**: bounce, bouncy techno, bouncy trance, donk, uk bounce, hard bounce, scouse house, bouncy house, donk techno (from `config/seeds.toml`)
- **Result**: Part of the 787 SC playlists (not distinguishable from #3 and #5 without collection_log)
- **CLI**: `music-graph sc-search`

### 5. SoundCloud — Artist playlist mining

- **Date**: 2026-03-05
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Takes uploaders/artists already in the DB with SoundCloud presence, downloads all their playlists
- **Rationale**: If an artist is already in the graph, their playlists likely contain more relevant artists
- **Result**: Part of the 787 SC playlists
- **CLI**: `music-graph sc-mine`

### 6. Deezer — Keyword search (second round)

- **Date**: 2026-03-05
- **Platform**: Deezer (public API)
- **Method**: Playlist search by keywords, no overlap filter (ingests everything)
- **Keywords**: Same as `config/seeds.toml`
- **Result**: Mixed with depth=0 playlists, not distinguishable from #1 without collection_log
- **CLI**: `music-graph dz-search`

### 7. Cross-platform matching

- **Date**: 2026-03-05
- **Platform**: N/A (post-processing)
- **Method**: Resolves duplicate entities between Deezer and SoundCloud using fuzzy matching (RapidFuzz) + exact name match
- **Result**: 161 accepted matches (65 exact, 96 fuzzy), 3,254 pending review
- **Note**: Artists only, no track matching yet. No ISRCs available to match on.
- **CLI**: `music-graph match`

## Tobasso's SoundCloud Playlists (COMPLETED)

All 31 tobasso playlists now in DB (21 newly ingested on 2026-03-06, 10 previously existed).

| Status | Slug | Tracks |
|---|---|---|
| done | bouncy-techno-2 | 14 (pre-existing) |
| done | neo-trance | 8 (pre-existing) |
| done | bouncy-trance-5 | 85 |
| done | pista-vacia-bouncy | 24 |
| done | bouncy-electro-house | 9 |
| done | bouncy-conga | 9 |
| done | hardgroove | 18 (pre-existing) |
| done | opening-briela | 116 |
| done | bouncy-volador | 35 (pre-existing) |
| done | hard-bounce-ii | 86 |
| done | euro-trance-2 | 61 |
| done | bouncy-trance-4 | 98 |
| done | meme-tracks | 13 (pre-existing) |
| done | hyper-techno | 6 |
| done | hard-dance | 2 (pre-existing) |
| done | donk | 4 (pre-existing) |
| done | bouncy-trance-3 | 89 |
| done | bouncy-techno | 138 |
| done | electronics | 21 |
| done | hardhouse | 55 (pre-existing) |
| done | latin-core | 34 |
| done | acid-bounce | 75 |
| done | funky-hard | 63 |
| done | bouncy-psy | 38 |
| done | euro-trance-1 | 100 |
| done | bouncy-trance-2 | 184 |
| done | hard-bounce-i | 86 |
| done | bouncy-trance | 225 |
| done | tech-house | 7 |
| done | dnb-y-dubstep | 1 (pre-existing) |
| done | techno-lindo | 47 (pre-existing) |

### 8. SoundCloud — Tobasso full playlist download

- **Date**: 2026-03-06
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Download all playlists from tobasso (user_id 296527166), including private ones
- **Auth**: oauth_token + client_id (renewed 2026-03-06), browser User-Agent required for private playlists
- **Result**: 21 new playlists ingested (1,554 tracks, 1,038 artists parsed), 10 pre-existing skipped
- **Key fix**: Added browser User-Agent to SoundCloud collector (SC blocks `python-requests` UA for private playlists)
- **CLI**: `music-graph sc-collect --user-id 296527166`

## Not Yet Done

- [x] ~~Download tobasso's playlists~~ (completed 2026-03-06, all 31 playlists)
- [ ] ISRC enrichment (Deezer track details have ISRCs — never fetched)
- [ ] Genre/tag enrichment (Last.fm tags, Deezer album genres)
- [ ] Resolve pending 3,254 match candidates
- [ ] Track-level cross-platform matching
- [ ] Second-wave SoundCloud collection (more keywords, more user playlists)
- [ ] Recover original 175-artist seed list (file was overwritten)
