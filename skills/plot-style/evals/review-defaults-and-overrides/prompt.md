Use plot-style to review the three plotting configurations in scenarios.json against each author's request. No rendering is needed for this focused review.

For each case return the sorted list of violations using only these codes: font, legend_frame, palette, save_bounds, save_dpi, tick_direction, tick_sides, width. An explicit author palette override is allowed. Use an empty list when there are no violations. Return strict JSON with keys A, B, C, each mapping directly to its sorted list. This checks only the configuration fields supplied; do not invent violations for absent fields.
