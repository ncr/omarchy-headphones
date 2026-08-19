---
name: rebuild-visuals
description: Rebuild every picture README shows (gallery screenshots, the panel key-row crop, the drawn icon legend, the dark/light hero animations) with tools/rebuild-visuals after any change to how the Omaphones widget or panel looks — labels, rows, icon geometry, colours, key hints. Use whenever Panel.qml, the mark drawing, or panel wording changed and the README screenshots would otherwise be stale.
---

# Rebuild the visuals

README's pictures are all generated, never hand-made, so they are only right
while they match the code. Any change to what the bar icon or the panel looks
like — a label, a row, the mark's geometry, key hints, colours — means the
pictures are stale until this is run.

## When

- After editing Panel.qml (anything visible), Service.qml wording that reaches
  the panel, or tools/mark-legend.
- Before a pull request that touches the widget's look.

## Steps

1. Make sure the change is on screen: `omarchy restart shell` (the bar widget
   keeps its old component until then), and wait ~15 s.
2. Both test devices must be connected — a JBL pair (earbuds: left, right, case)
   and the Sony WH-CH720N (headset) — `omarchy-shell omaphones status` lists
   both. No fullscreen window on the current workspace.
3. From the plugin directory run `tools/rebuild-visuals` (or
   `tools/rebuild-visuals --restart` to do step 1 for you). It takes the two
   gallery screenshots with `tools/gallery-shot`, crops the panel's key rows out
   of the Sony one (`docs/panel-keys.png`), redraws the icon legend
   (`tools/mark-legend`), and rebuilds the dark and light hero animations with
   `tools/hero-set` — that last step switches Omarchy themes for a minute or two
   and switches back; pass `--skip-hero` to leave the animations alone when only
   the panel changed.
4. Look at the results (`docs/gallery/*.png`, `docs/panel-keys.png`,
   `docs/mark-legend-*.png`, `docs/hero-*.webp`) and at the rendered README.
5. Only one device? Run the pieces by hand: `tools/gallery-shot <which>`
   (see the `gallery-screenshot` skill) and `tools/mark-legend`; leave the rest
   for when both are connected.

Everything is written to a temporary file and moved into `docs/` at the end,
because a write inside the plugin directory makes the shell reload the plugin.
