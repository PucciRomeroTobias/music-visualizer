# Architecture — music-graph

## Core Philosophy: Platform-Agnostic Data

The fundamental principle of this project is that **data is independent of its source platform**. Tracks, artists, and their relationships exist as canonical entities — Deezer, SoundCloud, Spotify, or any future collector are just *windows* into the same musical universe.

A track is a track, an artist is an artist. Whether we discovered them via a Deezer playlist or a SoundCloud upload doesn't matter for graph construction. The platform-specific details live in Source tables; the canonical entities are what the graph operates on.

This means:
- A track found on both Deezer and SoundCloud should be **one node** in the graph, not two.
- An artist with presence on multiple platforms should be **one node**, accumulating edges from all platforms.
- Playlists from any platform contribute equally to co-occurrence edges.
- The graph gets richer with each new collector, not fragmented.

## System Overview

```
Collect --> Store --> Match --> Build Graph --> Export
           (raw)   (canonical)  (co-occurrence)   (viz)
```

| Phase | Description |
|---|---|
| **Collect** | Gather tracks, playlists, and artists from any source platform |
| **Store** | Persist raw source data + canonical entities in SQLite |
| **Match** | Resolve cross-platform entities: merge same track/artist across platforms |
| **Build Graph** | Construct weighted co-occurrence graphs (tracks and artists) |
| **Export** | Output to GEXF, GraphML, JSON for visualization tools |

## Data Model

### Canonical + Source Pattern

Each entity has a **canonical record** (platform-agnostic) and one or more **source records** (platform-specific). This is the core of multi-platform support.

```
Track (canonical_title, canonical_artist_name, isrc, duration_ms)
  <- TrackSource (platform=DEEZER, platform_id, title, artist_name, raw_json)
  <- TrackSource (platform=SOUNDCLOUD, platform_id, title, artist_name, raw_json)

Artist (canonical_name)
  <- ArtistSource (platform=DEEZER, platform_id, name, raw_json)
  <- ArtistSource (platform=SOUNDCLOUD, platform_id, name, raw_json)

Playlist (platform, platform_id, name, owner_name)
PlaylistTrack (playlist_id, track_id, position)
TrackArtist (track_id, artist_id, role)
```

### Cross-Platform Matching

Matching happens at ingest time and in a post-processing pass:

**At ingest time (Ingester):**
- ISRC exact match: if a new track has an ISRC already in the DB, reuse the canonical Track
- Platform dedup: same (platform, platform_id) never creates duplicates

**Post-processing (MatchResolver):**
- Artist name matching: normalized name comparison + rapidfuzz token_sort_ratio
- Track matching: normalized (artist + title) + duration tolerance (< 5s difference)
- Results stored in `match_candidate` table with confidence scores
- High-confidence matches (>= 90) auto-accepted; lower ones flagged for review
- Accepted matches merge Source records under one canonical entity

### Staging Tables

- `expand_candidate`: Persists intermediate state for the expand pipeline (candidate playlists discovered but not yet probed/ingested). Enables batch-resumable execution.
- `match_candidate`: Stores proposed cross-platform entity matches with confidence and status.

## Collection Pipeline

### Multi-Platform Collectors

Each platform implements `AbstractCollector` protocol:
- `search_playlists(query, limit)` -> `list[RawPlaylist]`
- `get_playlist_tracks(playlist_id)` -> `list[RawTrack]`
- `get_artist_details(artist_id)` -> `RawArtist`
- `search_tracks(query, limit)` -> `list[RawTrack]`

Raw data classes (`RawTrack`, `RawPlaylist`, `RawArtist`) are platform-agnostic intermediaries. Each collector translates platform-specific API responses into these. The Ingester then stores them as canonical + source records.

### Current Collectors

| Collector | Status | Auth | Rate Limit |
|---|---|---|---|
| **Deezer** | Working | None | ~50 req/5s |
| **SoundCloud** | Planned | oauth_token + client_id | ~2 req/s |

### Pipelines

**seed_from_artists**: Genre keyword search on Deezer, filtered by SoundCloud artist overlap. Entry point for initial data.

**expand**: BFS expansion via related artists. Phases: discover related artists -> search their playlists -> probe for overlap -> ingest qualifying playlists. All phases persist to DB for batch resumability.

**Batch execution**: All pipelines respect a `max_minutes` time budget (default 15 min). Safe to interrupt — each commit is atomic, and re-running picks up where it left off.

## Graph Construction

### Bipartite Projection

Raw data forms a **bipartite graph**: playlists and tracks (or playlists and artists).
Two tracks are connected if they co-occur in at least one playlist, *regardless of which platform the playlist came from*.

**Edge weight** options:
- Raw co-occurrence count
- Jaccard similarity (shared / union of playlists)
- TF-IDF weighted (down-weight tracks that appear in many playlists)

### Two Graph Types

**Track graph**: Nodes = canonical tracks, edges = playlist co-occurrence. Cross-platform tracks that were matched appear as single nodes with edges from all their playlists.

**Artist graph**: Nodes = canonical artists, edges = weighted by shared playlist appearances. An artist present on both Deezer and SoundCloud accumulates edges from both platforms' playlists.

### Node Attributes

- **Track nodes**: title, artist, ISRC, duration, genres, source platforms
- **Artist nodes**: name, genres, tags, track count, source platforms

## Export Formats

| Format | Target Tool | Notes |
|---|---|---|
| **GEXF** | Gephi | Full attribute support, community detection |
| **GraphML** | General | Interoperable XML format |
| **JSON** | Custom viz / D3.js | Node-link format for web visualization |

## Design Decisions

| Decision | Rationale |
|---|---|
| **SQLite** | Zero-config, single-file DB, sufficient for 100K+ tracks |
| **SQLModel** | Type-safe ORM that combines SQLAlchemy + Pydantic |
| **NetworkX** | Pure Python graph library, rich algorithm set, easy GEXF/GraphML export |
| **rapidfuzz** | Fast fuzzy string matching for cross-platform entity resolution |
| **No async** | API rate limits are the bottleneck, not I/O — async adds complexity without benefit |
| **Canonical + Source** | Core pattern enabling platform-agnostic graph construction |
| **Batch execution** | Max 15 min batches with DB persistence to prevent data loss |

## Future Work

- **Visualization phase**: interactive web-based graph explorer
- **Last.fm enrichment**: tag-based genre classification and similarity edges
- **Community detection**: automated genre cluster discovery using Louvain/Leiden
- **MusicBrainz enrichment**: ISRC-based cross-platform track resolution
