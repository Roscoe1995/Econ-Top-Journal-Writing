# Common Visual Style

Use one restrained visual system across the paper. The reader should notice the evidence, not the graphics software.

## Typography

- Match the manuscript's font family unless the journal requires otherwise.
- English papers: use a serif manuscript font for table text when possible; use clear sans-serif labels only if the plotting system already does so consistently.
- Chinese papers: use the manuscript's Chinese typeface chain; keep numerals and Latin variable names visually compatible.
- Axis labels, tick labels, legends, and table notes usually sit in the 8-10 pt range in final output.
- Do not embed large titles inside plots when the caption already carries the title.

## Lines, Points, And Intervals

- Main line: about 2-2.5 pt in final output.
- Secondary line: about 1.5-2 pt, with dashed or dotted style if categories need grayscale distinction.
- Confidence intervals: thinner lines, capped intervals, or light neutral bands.
- Points: visible but not oversized; keep markers consistent within a figure family.
- Bars: muted fill, no heavy outlines unless bars overlap.

## Color

- Color must encode a real distinction: treatment/control, period, group, geography, uncertainty, or sign.
- Use one focal color and neutral gray for most two-series figures.
- Use sequential palettes for magnitude maps and diverging palettes only when zero or a policy threshold is meaningful.
- Avoid decorative gradients, saturated rainbow palettes, red-green pairs, and near-identical pastel series.

## Grids, Borders, And Backgrounds

- Prefer white backgrounds.
- Use light horizontal gridlines only when they help read values.
- Keep a zero line, policy cutoff line, or event-time line when it is part of the identification story.
- Avoid thick plot boxes and dense vertical gridlines.

## Tables

- Tables should be visually quiet: booktabs-style horizontal rules, no vertical rules, no colored coefficient cells.
- Align decimals and keep coefficient/standard-error pairs close.
- Use panel labels to organize outcomes, samples, or mechanisms instead of forcing too many columns into one table.

## Bilingual Output

- English captions use `Table`, `Figure`, and `Notes:`.
- Chinese captions use `表`, `图`, and `注：`.
- Write every reader-visible functional and variable label in the manuscript language. Retain only standard mathematical symbols, established abbreviations, formal classification codes, or proper names, and define them in the reader's language when they are not self-explanatory. Code use alone never makes an internal identifier suitable for display.
- Maintain separate English and Chinese display-label maps. Do not default to literal translation or mixed-language labels; require the two versions to preserve the same concept, unit, transformation, baseline, and comparison direction.
- Keep units, sample definitions, and standard-error descriptions in the language of the manuscript.

## Check

The same visual grammar should recur across the paper: same treatment color, same control color, same CI style, same font scale, same note format, and same export quality.
