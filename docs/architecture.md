# Architecture — music-graph

## System Overview

```
Collect --> Store --> Match --> Project --> Build Graph --> Export
```

| Phase | Description |
|---|---|
| **Collect** | Gather tracks, playlists, and artists from source platforms |
| **Store** | Persist raw and canonical data in SQLite |
| **Match** | Deduplicate tracks across sources using ISRC and fuzzy matching |
| **Project** | Build bipartite projection from playlist-track relationships |
| **Build Graph** | Construct weighted co-occurrence graph with pluggable algorithms |
| **Export** | Output to GEXF, GraphML, and JSON for visualization tools |

## Data Model

### Canonical + Source Pattern

Each entity has a **canonical record** (platform-agnostic) and one or more **source records**
(platform-specific).

```
CanonicalTrack (isrc, title, artist_name)
  <- SpotifyTrack (spotify_id, canonical_track_id, ...)
  <- SoundCloudTrack (soundcloud_id, canonical_track_id, ...)  # future

CanonicalArtist (name, normalized_name)
  <- SpotifyArtist (spotify_id, canonical_artist_id, genres[], ...)
  <- LastfmArtist (lastfm_url, canonical_artist_id, tags[], ...)  # future

Playlist (source, source_id, name, description)
PlaylistTrack (playlist_id, canonical_track_id, position)
```

This pattern allows merging data from multiple platforms while preserving source-specific metadata.

## Collection Pipeline

### BFS from Seed Keywords

1. Search Spotify for playlists matching seed keywords ("bounce", "donk", "bouncy techno", etc.)
2. For each playlist, fetch all tracks
3. For each track's artists, fetch artist details (genres)
4. Discover new playlists by searching for artist names + genre terms
5. Repeat with BFS, bounded by depth limit and relevance scoring

### Relevance Scoring

Playlists are scored by keyword density in title/description to avoid drifting
into unrelated genres. Low-scoring playlists are stored but excluded from the core graph.

## Graph Construction

### Bipartite Projection

Raw data forms a **bipartite graph**: playlists and tracks.
Two tracks are connected if they co-occur in at least one playlist.

**Edge weight** = number of shared playlists (simplest) or a pluggable function:
- Raw co-occurrence count
- Jaccard similarity (shared / union of playlists)
- TF-IDF weighted (down-weight tracks that appear in many playlists)

### Node Attributes

- **Track nodes**: title, artist, ISRC, genres (from artist), tags (from Last.fm)
- **Artist nodes** (in artist-projection mode): genres, tags, track count

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
| **No async** | Spotify rate limit is ~5 req/s — async adds complexity without benefit |

## Future Work

- **Visualization phase**: interactive web-based graph explorer
- **SoundCloud collector**: access niche tracks not on Spotify
- **Last.fm enrichment**: tag-based genre classification and similarity edges
- **Community detection**: automated genre cluster discovery using Louvain/Leiden
