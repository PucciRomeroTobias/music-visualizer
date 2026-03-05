# SoundCloud API Access — Current State

## Official API Status

- SoundCloud **shut down public API registration** in 2019
- Existing registered apps still work, but no new client IDs are issued
- Official docs at `developers.soundcloud.com` are stale and incomplete

## Unofficial Access Methods

### soundcloud-v2 Library

- Python package that wraps SoundCloud's internal v2 API
- Handles client ID extraction and request signing
- Actively maintained as of early 2026, but breaks periodically

### Direct API Endpoints

The internal API at `api-v2.soundcloud.com` is accessible with a valid `client_id` parameter.

**Client ID extraction:**
1. Fetch any SoundCloud embed page (e.g., `https://w.soundcloud.com/player/?url=...`)
2. Parse the JavaScript bundles referenced in the HTML
3. Extract the `client_id` string from the bundle code
4. IDs rotate periodically — extraction must be automated

### Key Endpoints

| Endpoint | Description |
|---|---|
| `/search` | Search across tracks, playlists, users. Query param `q`. |
| `/playlists/{id}` | Full playlist with track listing |
| `/tracks/{id}` | Track metadata including tags, genre, user |
| `/users/{id}` | User profile and metadata |
| `/users/{id}/tracks` | Paginated list of user's uploads |

## Rate Limits

- **Unknown** — no official documentation
- Empirically, aggressive crawling triggers temporary IP blocks
- Recommended: stay under 2 req/s, add jitter between requests

## Risks

- Endpoints **change without notice** — field names, pagination format, auth requirements
- Client ID extraction can break with frontend redesigns
- No SLA, no support, no guarantees

## Project Plan

SoundCloud integration is a **future phase**. The current focus is Spotify + Last.fm.
SoundCloud's user-generated tags make it valuable for discovering niche genres
that Spotify's curated taxonomy misses.
