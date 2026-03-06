# CLAUDE.md — music-graph

## What This Project Is

**music-graph** maps the underground electronic music scene — specifically **bounce, bouncy techno, bouncy trance, donk, UK bounce, hard bounce, scouse house, and neo rave** — by building co-occurrence graphs from playlist data across multiple platforms.

These micro-genres **do not exist as formal categories** in any major platform's taxonomy. They must be discovered through keyword search, playlist co-occurrence, tag aggregation, and artist overlap. This project makes that invisible scene visible.

The end goal is an **interactive artist graph visualization** on [nowarmup.com.ar](https://nowarmup.com.ar), where users can explore how artists in this scene connect to each other.

## Architecture

```
Collect → Store → Match → Project → Build Graph → Export → Visualize
```

- **Collect**: BFS expansion from seed keywords across platforms (Deezer working, Spotify blocked, SoundCloud planned)
- **Store**: SQLite via SQLModel. Canonical + Source pattern — entities are platform-agnostic, sources are per-platform metadata
- **Match**: Cross-platform deduplication via ISRC and fuzzy matching (RapidFuzz, MusicBrainz)
- **Build Graph**: Bipartite projection (playlist↔track) into weighted artist co-occurrence graph. Pluggable algorithms: raw, Jaccard, PMI, cosine
- **Export**: GEXF (Gephi), GraphML, JSON (for viz)
- **Visualize**: Sigma.js + Graphology, 2D WebGL rendering with community detection coloring

## Design Philosophy

### Platform-agnostic data
Track/Artist canonical entities are independent of source platform. Deezer, SoundCloud, etc. are just windows into the same musical universe. The graph operates on canonical entities only — platform is metadata.

### Performance-first visualization
The visualization **must be usable on mobile phones**. This means:
- Use WebGL rendering (Sigma.js), never SVG/DOM-based graph rendering
- Keep bundle size minimal — no heavy frameworks for the viz layer
- Pre-compute layouts server-side (don't run force-directed layout in the browser)
- Use log-scale node sizing to avoid extreme size variation
- Lazy-load data where possible
- Target 60fps on mid-range mobile devices

## Visual Identity — nowarmup.com.ar

The visualizer is part of the nowarmup brand. All UI must follow this aesthetic:

### Color Palette
```css
--negro-profundo: #06030b;    /* Background — deep black with purple undertone */
--violeta-oscuro: #2e1d35;    /* Panels, hover states */
--violeta-medio: #361160;     /* Accents, scrollbar, borders */
--gris-claro: #aaa1b1;        /* Body text */
--rosa-neon: #aa23b1;          /* Primary accent — labels, glows, highlights */
```

### Community node colors (neon/rave palette)
```
#aa23b1 (rosa-neon), #06b6d4 (cyan), #f97316 (orange), #22d3ee (electric blue),
#a855f7 (purple), #14b8a6 (teal), #f43f5e (rose), #eab308 (yellow),
#3b82f6 (blue), #10b981 (emerald), #ec4899 (pink), #8b5cf6 (violet)
```

### Typography
- **Display/headings**: Eurostile Extended family
- **Body/UI**: Eurostile, fallback to system sans-serif
- **Graph labels**: Inter, system-ui (for legibility at small sizes)
- **Style**: uppercase, letter-spacing 0.1–0.15em for labels and headings

### UI Patterns
- Panels: semi-transparent dark backgrounds (`rgba(6, 3, 11, 0.92)`) with neon-pink borders (`rgba(170, 35, 177, 0.4)`)
- Neon text-shadow on section titles: `0 0 8px var(--rosa-neon), 0 0 12px var(--rosa-neon)`
- Scrollbars: thin, rosa-neon thumb on negro-profundo track
- Animations: subtle pulse effects, smooth transitions (0.2–0.3s ease)
- Mobile: bottom-sheet pattern for detail panels, responsive search bar

## Tech Stack

### Backend (data pipeline)
- **Python 3.11+**, PEP 8, type hints, Google-style docstrings
- **SQLModel** (SQLAlchemy + Pydantic) with SQLite
- **NetworkX** for graph construction and algorithms
- **Typer** CLI, **Loguru** logging, **RapidFuzz** for fuzzy matching
- **requests** for API calls (always with `timeout=(10, 30)`)

### Frontend (visualization)
- **Sigma.js** + **Graphology** for WebGL graph rendering
- **Vite** for bundling
- Vanilla JS (no React/Vue in the viz layer — keep it lean for mobile perf)

### nowarmup.com.ar (main site, separate repo)
- React 19 + TypeScript + Vite + styled-components
- The visualizer will be embedded/linked from this site

## Collection Tracking

Two levels of tracking:

### 1. Human-readable log — `docs/collection_log.md`

**After every collection run, update `docs/collection_log.md`** with:
- What was collected (platform, method, keywords, filters)
- How many items resulted (playlists, tracks, artists)
- The CLI command used
- Updated DB state totals at the top of the file

This is the source of truth for "what has been done". An agent should read this file before deciding what to collect next.

### 2. Code-level resumability

- **`playlist.tracks_collected`**: boolean flag — `True` only after all tracks from a playlist have been fetched and committed. Allows resuming interrupted runs.
- **`BFSOrchestrator`**: on startup, loads already-seen playlists and artists from the DB, skips completed work.

### Rules for new collectors

When adding a new collector or collection method:
1. Mark `playlist.tracks_collected = True` only after all tracks are committed
2. Load already-processed state from DB on startup, never rely on in-memory sets alone
3. Commit after each playlist (not at the end) to avoid losing progress
4. **Update `docs/collection_log.md`** after the run completes

## Workflow

- **`main` worktree** (`music-visualizer/`): run collections, has the live DB in `data/`
- **Feature worktrees** (`music-visualizer-feature-*/`): code-only, no DB — `data/` is gitignored and not shared across worktrees

## Key Conventions

- Long-running processes: batch in **max 15-minute chunks**, resumable, commit progress to DB after each batch
- All `requests.get()` calls **must** include `timeout=(10, 30)`
- Seeds and genre scope defined in `config/seeds.toml`
- Settings (rate limits, thresholds) in `config/settings.toml`
- DB path: `data/music_graph.db`
- Graph exports: `data/exports/`

## Project Structure

```
config/          # seeds.toml, settings.toml
data/            # SQLite DB, exports, seed data (gitignored)
docs/            # architecture, research notes
src/music_graph/
  cli.py         # Typer CLI (collect, stats, collection-status, build-graph)
  config.py      # Config loader (TOML + .env)
  db.py          # Engine + session management
  collectors/    # Platform collectors (Deezer, Spotify, base, rate_limiter)
  models/        # SQLModel entities (track, artist, playlist, genre, matching, collection_log)
  pipeline/      # Orchestration (collect, build_graph)
  graph/         # Edge weights, projections, export
  matching/      # Cross-platform matching (fuzzy, musicbrainz, matcher)
```
