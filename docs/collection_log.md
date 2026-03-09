# Collection Log

Record of all data collection runs. Update this file after every collection.

## Current DB State

- **Playlists**: 219 Deezer + 1,223 SoundCloud = 1,442 total
- **Tracks**: 76,838 canonical
- **Artists**: 22,304 canonical
- **Relevance tiers**: 1,442 playlists judged — ALL (486 tier 1, 497 tier 2, 252 tier 3, 207 tier 4)
- **Genres**: 0 (enrichment not yet run)
- **ISRCs**: 0 (enrichment not yet run)
- **Cross-platform matches**: 161 accepted (65 exact + 96 fuzzy, artists only), 3,254 pending
- **Last updated**: 2026-03-07

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

### 9. Multi-provider LLM Judge + Judged Deezer Search

- **Date**: 2026-03-06
- **Platform**: Deezer (public API)
- **Method**: Keyword search with BounceJudge LLM filter — only playlists scoring tier 1-2 (score >= 5) get ingested
- **Judge**: Multi-provider LLM client (Ollama gemma2:9b primary, Gemini 2.5-flash/2.0-flash fallback, Groq llama-3.3-70b/gemma2-9b-it fallback)
- **Profile**: `config/bounce_profile.md` — tightened to reject false positives (generic trance, vocal trance, decade compilations)
- **Keywords**: 27 expanded keywords covering bouncy techno, neo rave, hardgroove, hard house, eurotrance, acid techno, schranz, etc.
- **Result**: 31 Deezer playlists judged and tiered (from first `dz-judged` run)
- **CLI**: `music-graph dz-judged`

### 10. SoundCloud — Label mining (judged)

- **Date**: 2026-03-06 → 2026-03-07
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Search for 25 known bounce/neo rave labels, fetch their playlists, filter via BounceJudge
- **Labels**: Ambra, Polyamor Records, Elemental Records, MASS, Molekül, SPEED, Reboot Records, H33 Records, ELOTRANCE, Sachsentrance, NEOTRANCE, Nektar Records, Bipolar Disorder Rec, Groove Street Berlin, GRS TECHNO, OBSCUUR, SYNTHX RECORDS, POWERTRANCE, Yeodel Rave, EXILE TRAX, Neon Dreams Cologne, DEAD END, Crimsonc9, SONICFLUX, GOTD
- **Judge**: Ollama gemma2:9b (local, no rate limits, ~12s/playlist)
- **Result**: 242 new SC playlists ingested, 240 judged (157 tier 1, 83 tier 2, 0 rejected — labels are high-signal)
- **CLI**: `music-graph sc-labels --max-minutes 15` (multiple batches)

### 11. SoundCloud — Label mining wave 2 (IN PROGRESS)

- **Date**: 2026-03-07
- **Platform**: SoundCloud (unofficial API v2)
- **Method**: Expanded label list (37 labels) — labels discovered in DB + known scene labels
- **Labels processed so far** (~8/37): Throne Room Records, Sopranos Bounce, COUP, Ramba Zamba Music, VERKNIPT (partial — user "Chemtrailz" has 49 playlists, still processing)
- **Labels remaining** (~29): Beatroot Records, TripleXL, RAVE ALERT, INITIALIZE, unregular, Deadly Alive, NOTMYTYPE, Need More Speed, Selicato, Taapion, Sound Transitions, Ritmo Fatale, TNBN Records, Exhausted Modern, Kneaded Pains, Rave Instinct, Warehouse Rave, Bounce Inc, FCKNG SERIOUS, Filth on Acid, Hardgroove Records, Toolroom Trax, ÄVEM Records, Voltage Records, Bounce Heaven, This Is Bounce UK, Donk Records, Sick Slaughterhouse, Kuudos Records, Possession, DSNT, Perc Trax
- **Judge**: Ollama gemma2:9b (local) with Gemini/Groq fallback
- **Result so far**: 5 batches × 15 min, 173 playlists ingested, ~96 rejected (~36% rejection rate)
- **Status**: PAUSED — resume with `music-graph sc-labels --wave 2 --max-minutes 15`
- **CLI**: `music-graph sc-labels --wave 2 --max-minutes 15`

### 12. Bulk playlist judging (all existing playlists)

- **Date**: 2026-03-07
- **Platform**: N/A (post-processing, DB-only)
- **Method**: Ran `judge-existing` on all 987 playlists without `relevance_tier`. Reads 15-track sample from DB, sends to BounceJudge LLM, writes tier + genre back. No platform API calls needed.
- **Judge**: Ollama gemma2:9b (primary), Gemini/Groq as fallback (rate-limited on free tier, mostly fell back to Ollama)
- **Concurrency**: Another SC label mining process was writing to the DB simultaneously. Enabled WAL mode on SQLite + added commit-with-retry logic to avoid lock conflicts.
- **Batches**: 12 × 15 min (~3 hours total), ~80-120 playlists per batch
- **Result**: 987 playlists judged (+ 179 new playlists from concurrent collection also judged). Final state: 0 playlists without tier.
- **Tier distribution (all 1,442 playlists)**: 486 tier 1, 497 tier 2, 252 tier 3, 207 tier 4
- **CLI**: `music-graph judge-existing --max-minutes 15` (repeated 12 times)

## Not Yet Done

- [x] ~~Download tobasso's playlists~~ (completed 2026-03-06, all 31 playlists)
- [x] ~~SC label mining wave 1~~ (completed 2026-03-07, 25 labels, 240 playlists judged)
- [ ] SC label mining wave 2 — ~29/37 labels remaining (resume `sc-labels --wave 2`)
- [x] ~~Judge existing playlists~~ (completed 2026-03-07, all 1,442 playlists tiered)
- [ ] Deezer judged search — second round with corrected profile + Ollama
- [ ] ISRC enrichment (Deezer track details have ISRCs — never fetched)
- [ ] Genre/tag enrichment (Last.fm tags, Deezer album genres)
- [ ] Resolve pending 3,254 match candidates
- [ ] Track-level cross-platform matching
- [ ] Second-wave SoundCloud collection (more keywords, more user playlists)
- [ ] Recover original 175-artist seed list (file was overwritten)
