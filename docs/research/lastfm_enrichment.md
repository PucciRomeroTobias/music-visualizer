# Last.fm API — Enrichment Layer

## Access

- **Free API key** — register at `last.fm/api/account/create`
- No OAuth needed for read-only tag/similarity data
- Rate limit: **5 requests per second** (documented and enforced)

## Relevant Endpoints

### track.getTopTags

- Input: artist name + track name (or MusicBrainz ID)
- Returns: list of user-generated tags with `count` (relative weight 0-100)
- Quality: excellent for electronic subgenres — users tag with specific names like
  "bouncy techno", "donk", "UK bounce" that formal taxonomies ignore

### artist.getTopTags

- Input: artist name (or MusicBrainz ID)
- Returns: same tag format as track.getTopTags
- Useful for classifying artists when track-level tags are sparse

### artist.getSimilar

- Input: artist name (or MusicBrainz ID)
- Returns: list of similar artists with `match` score (0.0 to 1.0)
- Source: Last.fm's own collaborative filtering model based on listening patterns
- Very useful for expanding the artist graph beyond playlist co-occurrence

### track.getSimilar

- Input: artist name + track name
- Returns: similar tracks with match scores
- **Less reliable** than artist.getSimilar — coverage is spotty for niche tracks
- Use as supplementary signal only

## Tag Quality Assessment

| Genre Space | Tag Quality | Notes |
|---|---|---|
| Electronic subgenres | Excellent | Users are precise: "hard bounce", "scouse house", "donk" |
| Mainstream pop/rock | Noisy | Too many generic tags dilute signal |
| Regional scenes | Good | UK-specific scenes well-represented |

## Use Case in This Project

Last.fm is an **enrichment layer**, not a primary data source:

1. Collect tracks and artists from Spotify playlists
2. Query Last.fm for tags on each track and artist
3. Use tags to validate genre classification from co-occurrence analysis
4. Use `artist.getSimilar` to discover artists not found via Spotify playlists
5. Feed similarity scores as additional edge weights in the graph

## Matching Strategy

- Match by **artist name + track name** (normalized: lowercase, strip parentheticals)
- Fall back to artist-level tags when track-level data is missing
- Cache aggressively — tag data is stable over time
