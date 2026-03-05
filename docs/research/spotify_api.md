# Spotify Web API — State as of March 2026

## Authentication

**Client Credentials Flow** is sufficient for this project. No user login required.

- `POST https://accounts.spotify.com/api/token` with `grant_type=client_credentials`
- Returns a Bearer token valid for 1 hour
- Scope: public catalog data only (no user library, no playback)

## Key Endpoints

### Search — `GET /v1/search`

- Query types: `playlist`, `track`, `artist`, `album`
- Pagination: `limit` (max 50), `offset` (max **1000**)
- Hard ceiling: offset + limit <= 1000. To go beyond, vary the query string.
- Market parameter recommended to get playable tracks with ISRCs.

### Playlist Items — `GET /v1/playlists/{id}/tracks`

- Returns up to **100 items per page** (`limit=100`)
- No offset ceiling — full pagination works via `next` URL
- Each item includes a simplified track object with `external_ids.isrc`

### Artist Details — `GET /v1/artists/{id}`

- Returns full artist object including **genres** array
- **No batch endpoint** since February 2026 — the multi-get `/v1/artists?ids=` was removed
- Each artist requires an individual request

## Rate Limits

- Approximate sustained throughput: **~5 requests/second**
- Exceeding returns `429 Too Many Requests` with a `Retry-After` header (seconds)
- No official published limits — the 5 req/s figure is empirical
- Back-off strategy: honor `Retry-After`, then resume with exponential back-off

## Data Model Notes

### Genres

- Genre tags live **only on artist objects**, never on tracks or albums
- Spotify's genre taxonomy is curated (not user-generated) — about 6,000 genres
- Many niche electronic subgenres are missing or aggregated into broader categories

### ISRC

- Available in `track.external_ids.isrc` — useful as a cross-platform canonical ID
- Not all tracks have one (remixes, bootlegs, DJ mixes often lack it)

## Restrictions (New Apps)

- **Audio Features** (`/v1/audio-features`) — no longer available for apps created after Nov 2024
- **Audio Analysis** (`/v1/audio-analysis`) — same restriction
- These endpoints are irrelevant for this project's graph-based approach
