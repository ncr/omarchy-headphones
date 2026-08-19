---
name: gallery-screenshot
description: Take the Omaphones gallery screenshot for one pair of headphones — fixed frame, empty workspace, the device's panel open under the bar — with tools/gallery-shot, and put it into README's Gallery. Use when adding a device row to README.md, when a PR needs a screenshot, or when the user asks for a panel screenshot of their headphones.
---

# Gallery screenshot

Every device in README's Gallery is shot the same way, by `tools/gallery-shot`,
so the pictures line up: 560×420 logical pixels rendered at scale 2 (always
1120×840), the bar along the top, the device's panel open and centred under its
icon, taken on an empty workspace so nothing else is in the frame.

## Steps

1. The headphones must be connected and followed by the widget:
   `omarchy-shell omaphones status` lists them. `<which>` below is a piece of the
   name, the address, or the brand of the mode backend (`sony`, `jbl`).
2. Run, from the plugin directory:

   ```bash
   tools/gallery-shot <which>                  # e.g. tools/gallery-shot jbl
   tools/gallery-shot <which> --mode ambient   # Sony: show the ambient dial, then restore the mode
   ```

   It prints the file it wrote: `docs/gallery/<brand-model>.png` (brand first
   when the name lacks it). `--out FILE` overrides. It switches to an empty
   workspace and back, opens and closes the panel, and restores the listening
   mode it found.
3. Open the file and check: the panel is whole, the bar is at the top, the
   battery rows and the mode row are there, nothing personal is in the frame.
4. Add the device to README.md: a row in the *Supported headphones* table, and
   a cell in the *Gallery* HTML table at the bottom — copy an existing `<td>`
   pair: the image cell `<td width="…"><img src="docs/gallery/<brand-model>.png"
   alt="Brand Model: what the panel shows" width="100%"></td>` in the first row
   and the caption cell `<td align="center">Brand Model — <a
   href="https://github.com/handle">@handle</a></td>` in the second; keep the
   `width` attributes equal across a row so the pictures render the same size
   (start a new two-column table after every two devices). One screenshot per
   device; do not reuse a picture elsewhere in the README.

## Everything at once

After a change to how the widget looks, `tools/rebuild-visuals` takes every
picture README shows (see the `rebuild-visuals` skill); this skill is for one
device.

## If it fails

- `the current workspace has a fullscreen window` — the person is watching or
  playing something; do not force it, ask them when it is a good moment (or
  they can set `GALLERY_SHOT_FORCE=1` themselves).

- `the widget follows no device matching` — connect the headphones, or use
  another piece of the name (`bluetoothctl devices` shows it).
- `the panel did not open` — the widget is not running or the shell is stale
  after an update: `omarchy restart shell`, then retry.
- The mode was not restored (rare, the headset answers late): set it back with
  `omarchy-shell omaphones setModeFor <mode> <which>`.
