# Design Guidelines — NO WARM UP

Visual identity guidelines for all NWUP digital products.
Based on the official brand manual (DG: Aldana Morales, NWUP 2026).

## Brand Essence

NO WARM UP is a community, producer collective, and party cycle dedicated to
high-energy electronic music (Bounce, Eurotrance, HardBounce) based in Buenos
Aires, Argentina. The visual identity reflects: **intensity, community,
movement, and contemporary nostalgia**.

## Color Palette

### Primary

| Name | Hex | RGB | Usage |
|---|---|---|---|
| Negro Total | `#000000` | 0, 0, 0 | Backgrounds, base color |
| Blanco Puro | `#FFFFFF` | 255, 255, 255 | Text, highlights |
| Violeta Neon | `#C02DEB` | 192, 45, 235 | Primary accent, glows, borders |

### Secondary

| Name | Hex | RGB | Usage |
|---|---|---|---|
| Rosa Neon | `#F000D8` | 240, 0, 216 | Secondary accent, highlights |
| Cian Electrico | `#65EDFA` | 101, 237, 250 | Tertiary accent, contrast |
| Gradiente | `#F000D8` -> `#C02DEB` -> `#65EDFA` | — | Backgrounds, decorative elements |

### Application in Visualization

- **Background**: Negro Total `#000000` (pure black)
- **Node colors**: Community-based palette anchored in Violeta Neon, Rosa Neon, Cian Electrico
- **Glows/Bloom**: Violeta Neon `#C02DEB` as primary glow color
- **Panel borders**: `rgba(192, 45, 235, 0.4)` (violeta neon at 40%)
- **Panel backgrounds**: `rgba(0, 0, 0, 0.92)` (negro total at 92%)
- **Labels/Text shadows**: Violeta Neon glow
- **Selected node**: White `#FFFFFF`
- **Dimmed nodes**: `#0a0014` (near-black with violet tint)

## Typography

### Primary — Eurostile

Used for: logotype, headings, labels, node labels in the graph.

- Weights: Regular, Medium, Bold, Heavy, Black
- Style: Regular + Italic
- Character: geometric, industrial, futuristic — fits the rave/techno identity

### Secondary — Inter

Used for: body text, stats, detail panel content, search input.

- Weights: Thin, Light, Regular, Medium
- Character: clean, modern, highly legible at small sizes

### Application in Visualization

- **Node sprite labels**: Eurostile/Inter bold, uppercase
- **Panel headings** (`#detail-name`): Eurostile bold, uppercase, letter-spacing 0.08em
- **Stat labels**: Eurostile, 8px, uppercase, letter-spacing 0.12em
- **Body text**: Inter, 11-13px

## Logo

The NWUP isotipo is a stylized 4-point star inside an orbital ellipse.
Available in: Violeta Neon, Rosa Neon, white, black, and gradient versions.

- **Do not** place other elements inside the protection area
- **Do not** modify proportions or colors outside the approved palette

## Visual Principles for the Graph

1. **Dark-first**: Pure black background, no grays. Content emerges from darkness.
2. **Neon accents**: Use Violeta Neon and Rosa Neon for glows, borders, and highlights — never as flat fills on large areas.
3. **Gradient as energy**: The violeta -> rosa -> cian gradient represents the energy flow. Use it directionally.
4. **Bloom = atmosphere**: Post-processing bloom creates the club/rave lighting feel. Keep it subtle (strength ~1.2).
5. **Uppercase, spaced typography**: All labels and UI text use uppercase with generous letter-spacing — mirrors the brand's typographic style.
6. **Minimal chrome**: Panels and UI should feel transparent/floating over the graph, not heavy boxes.

## CSS Variables Reference

```css
:root {
  --negro-total: #000000;
  --blanco-puro: #ffffff;
  --violeta-neon: #c02deb;
  --rosa-neon: #f000d8;
  --cian-electrico: #65edfa;
  --violeta-medio: #361160;
  --violeta-oscuro: #1a0a2e;
  --gris-claro: #aaa1b1;
  --panel-bg: rgba(0, 0, 0, 0.92);
  --panel-border: rgba(192, 45, 235, 0.4);
}
```
