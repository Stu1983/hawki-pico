# Case

A wall- or beam-mounted case for the Pico 2 W, with or without headers. ![preview](preview.png)

| File (`out/`) | What |
|---|---|
| `hawki_base.stl` | Base. Print open side up, no supports. |
| `hawki_lid_2colour.3mf` | Lid, already **face down**, with "Oil Monitor", the oil drop and "HAWKi" as a second object: give it the second filament (H2D: assign the other nozzle). The text is inlaid flush, 0.6 mm deep. |
| `hawki_lid.stl` + `hawki_lid_text.stl` | The same lid as two STLs, the right way up (flip them face down in the slicer). |

**Settings:** PETG, 0.2 mm layers, 3 walls, 20% infill. Use the default inner-then-outer wall order. Outside: 57.5 × 26.2 × 18.5 mm, 48 mm wide across the screw ears. Use about 4 mm countersunk wood screws.

**Fitting:**
- Drop the Pico onto the four pegs, USB end towards the opening. The pegs hold it 10 mm up, so soldered headers fit underneath.
- Push the lid on: its posts hold the board down. The lid is a friction fit, so prise it off at the corners.

**Button and LED:**
- The U-shaped tongue under "Oil Monitor" is a flexible button over BOOTSEL. Hold it for 5 seconds to clear a forgotten PIN.
- The small hole next to it shows the LED.
- The button, LED and USB positions are the ones from the Pico mount that fitted your MiSTer flap exactly.
- The button flexes along the print layers, which is why it must be printed face down.

**Changing it:** sizes are at the top of `make_case.py` (`python3 case/make_case.py`; needs `trimesh manifold3d shapely matplotlib`). For example:
- `BOOTSEL_X/Y`: where the button hole goes;
- `LIP_CLR`: a looser or tighter lid;
- `TEXT`, `SUB`: the words on the lid.
