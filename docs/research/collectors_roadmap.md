# Collectors Roadmap

Possible data sources for music-graph, ordered by viability.

## Working Now

### Deezer API
- **Status**: Implemented, working
- **Auth**: None required (public API)
- **Rate limits**: ~50 req/5s
- **Data**: Playlists with tracks, artist details, album genres, ISRC, search
- **Pros**: No auth, generous limits, good genre data via albums
- **Cons**: Smaller catalog than Spotify for niche genres

### Last.fm API
- **Status**: Planned (enrichment phase)
- **Auth**: Free API key
- **Rate limits**: 5 req/s
- **Data**: User-generated tags (excellent for niche genres), artist similarity, track tags
- **Pros**: Best source for niche electronic genre tags (bounce, donk, makina, etc.)
- **Cons**: No playlist data, enrichment-only

### MusicBrainz API
- **Status**: Partially implemented (ISRC lookup, artist matching)
- **Auth**: None (set user-agent)
- **Rate limits**: 1 req/s
- **Data**: 35M+ recordings, ISRCs, artist metadata, release groups
- **Pros**: Open data, excellent for cross-platform matching
- **Cons**: Slow rate limit, no playlists or genre tags

## Viable — Not Yet Implemented

### Tidal API
- **Status**: To research
- **Auth**: OAuth 2.0 (developer account needed)
- **Data**: High-quality catalog, playlists, curated content, genres
- **Pros**: Growing catalog, good electronic music coverage
- **Cons**: Developer access may be restricted, smaller user-generated playlist ecosystem

### SoundCloud (Unofficial)
- **Status**: Researched, future phase
- **Auth**: Unofficial — extract client_id from embed pages
- **Data**: Tracks, playlists, user uploads, tags
- **Pros**: Best source for underground/unsigned artists in bounce/donk scene
- **Cons**: No official API since 2019, endpoints change without notice, risk of breakage

### ListenBrainz
- **Status**: To research
- **Auth**: Free API
- **Data**: Listening history, user playlists (collaborative), recommendations
- **Pros**: Open source Last.fm alternative, growing community
- **Cons**: Smaller user base

### Bandcamp (Scraping)
- **Status**: To research
- **Auth**: No official API, would need scraping
- **Data**: Artist pages, tags, albums
- **Pros**: Many niche electronic artists self-release here
- **Cons**: No official API, scraping fragile, no playlists

### SpotifyScraper (Python library)
- **Status**: Available as fallback
- **Auth**: None (scrapes embed endpoints)
- **Data**: Track/album/artist metadata, public playlists
- **Pros**: Access Spotify data without API restrictions
- **Cons**: Rate limited (~100 req/min), can break with Spotify changes, scraping TOS risk

### Discogs API
- **Status**: To research
- **Auth**: OAuth or personal token
- **Data**: Release database, labels, genres/styles
- **Pros**: Detailed genre taxonomy (styles like "donk", "bouncy techno" exist), label info
- **Cons**: Physical release focused, no playlists or streaming data

## Not Viable

### Spotify API (Official)
- **Status**: Blocked
- **Why**: Dev Mode (Feb 2026) returns 403 on playlist tracks, artist top tracks, related artists, album tracks. Extended Quota Mode requires legal org + 250K MAU.
- **What works**: Search (10 results max), individual track/artist metadata (no genres)

### YouTube Music API
- **Status**: No public API
- **Why**: Only available through YouTube Data API v3 which doesn't expose Music-specific features (playlists, genres)
