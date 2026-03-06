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

### SoundCloud (Unofficial v2 API) — TESTED, READY TO IMPLEMENT
- **Status**: Proven viable — successfully extracted 1488 tracks from 22 private playlists (March 2026)
- **Auth**: `oauth_token` from browser cookies + `client_id` extracted from page scripts
  - `oauth_token`: found in SoundCloud cookies after login (format: `2-XXXXXX-USERID-XXXXXXXXXX`)
  - `client_id`: found in `<script>` tags on any SoundCloud page (format: 32-char alphanumeric)
  - Both can be extracted via Playwright browser automation (login → read cookies/scripts)
- **Base URL**: `https://api-v2.soundcloud.com`
- **Key endpoints tested**:
  - `GET /users/{userId}/playlists?client_id=...&limit=50` + `Authorization: OAuth {token}` → all playlists (including private)
  - `GET /tracks?ids={comma-separated-ids}&client_id=...` + `Authorization: OAuth {token}` → batch track details (up to 50 per request)
  - Playlist objects include full track list, but only first ~5 tracks have complete data (title, user); rest are ID-only and need batch fetching
- **Rate limits**: ~2 req/s seems safe (we used 200ms delay between batches without issues)
- **Data available**: Track title, duration, uploader username, track ID, permalink, genre tag, tag_list, waveform_url, artwork_url
- **Gotchas**:
  - SoundCloud "artists" are actually uploaders — labels/collectives (e.g., "Polyamor Records", "MILLI RECORDS") upload tracks by various artists
  - Real artist name is often embedded in track title (e.g., "DJ IP - ROCK THE PLACE" uploaded by "Polyamor Records")
  - Need title parsing with separators (` - `, ` – `, ` — `) to extract actual performing artist
  - Collaboration separators: ` & `, ` x `, ` b2b `, ` feat. `, ` ft. `
  - Common title prefixes to strip: `Premiere:`, `FREE DL`, `[Label]`
  - `oauth_token` may expire — needs periodic refresh via browser re-login
- **TODO — Implementation plan for SoundCloudCollector**:
  1. Store `oauth_token` and `client_id` in `.env` (extracted manually or via Playwright helper script)
  2. Implement `SoundCloudCollector(AbstractCollector)` with rate limiter (2 req/s, burst 5)
  3. `get_user_playlists(user_id)` → list private + public playlists
  4. `get_playlist_tracks(playlist_id)` → fetch full playlist, then batch-fetch missing tracks via `/tracks?ids=`
  5. Title parser to extract real artist names from track titles
  6. Map to `RawTrack`/`RawPlaylist`/`RawArtist` — use uploader as fallback artist, parsed title artist as primary
  7. Add CLI command: `music-graph collect --platform soundcloud --user-id {id}`
- **Pros**: Best source for underground/unsigned bounce/donk/trance artists, access to private playlists, no official API restrictions
- **Cons**: Unofficial API — endpoints can change without notice, token expires, scraping TOS risk

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
