# Capture-quality calibration

This is a measurement report for issue [#236](https://github.com/zexy2/mealog/issues/236).
The module is deliberately not wired into the meal pipeline, runner, gate, or
HTTP response. No provider call is needed.

## Measurement

`server/src/capture-quality.ts` decodes the non-interlaced 8-bit PNG forms in
the calibration set using Node's built-in `zlib`. It converts RGB/RGBA pixels
to luma with `round((299R + 587G + 114B) / 1000)`, then computes population
variance for:

- the 4-neighbour Laplacian over the interior pixels (`laplacianVariance`),
- all luma pixels (`textureVariance`), and
- `laplacianVariance / textureVariance`
  (`normalizedLaplacianVariance`), with the diagnostic `thresholdBand` cut at
  `0.10`, `0.15`, and `0.30`.

A genuinely uniform frame has zero texture variance, so the ratio is undefined
(`null`) and the measurement is marked `textureless`. It is not labelled
blurry. That explicit case is why a plain white plate does not become a blur
false positive merely because its unnormalised Laplacian variance is zero.

## Available distributions

The only available calibration images are the six coordinator-provided files
under `/tmp/mealog-adversarial/`. They are all known refusal/adversarial cases;
there are **zero real-food controls** in this set. The rows below are therefore
an observed adversarial distribution, not a food-quality validation set.

| image | known case | dimensions | texture variance | Laplacian variance | normalized score | threshold band |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `BULANIK RESIM.png` | blurred | 398×325 | 1372.554130 | 119.049239 | 0.086736 | below 0.10 |
| `BOS TABAK.png` | empty plate | 392×328 | 3728.459326 | 532.328904 | 0.142774 | 0.10–0.15 |
| `TELEFON EKRANINDA YEMEK.png` | screen | 418×322 | 2772.630133 | 754.643317 | 0.272176 | 0.15–0.30 |
| `OYUNCAK YEMEK.png` | toy | 380×325 | 1420.336427 | 557.855628 | 0.392763 | at or above 0.30 |
| `ANAHTARLIK KALEM.png` | non-food | 387×326 | 1028.448734 | 1047.761921 | 1.018779 | at or above 0.30 |
| `BIR BARDAKSU.png` | non-food | 383×321 | 702.633738 | 886.441623 | 1.261598 | at or above 0.30 |

For the known unusable set (`n=6`), the normalized-score distribution is:

| count | minimum | median | maximum |
| ---: | ---: | ---: | ---: |
| 6 | 0.086736 | 0.332470 | 1.261598 |

The required real-food distributions are unavailable: sharp `n=0`, mildly
blurred `n=0`, and heavily blurred `n=0`. The six refusal images also mix blur,
empty-plate, screen, toy, and non-food cases; they are not interchangeable
with a labelled real-food blur set.

## Candidate thresholds

These are diagnostic candidates only, and the module exposes their interval as
`thresholdBand`; this is not a production gate. The policy under test is “flag
when the normalized score is below the candidate”; textureless frames are
handled by the explicit textureless branch. `False rejects` require real-food controls,
which are absent. The observed catches are shown so the limitation is
quantified, but they are not a true-catch estimate for food photographs.

| candidate lower threshold | false rejects: real food | observed catches: known unusable |
| ---: | ---: | ---: |
| 0.10 | not measurable (0/0 controls) | 1/6 |
| 0.15 | not measurable (0/0 controls) | 2/6 |
| 0.30 | not measurable (0/0 controls) | 3/6 |

There is no defensible shipping threshold from this evidence. The real-food
distribution is missing, so false-reject counts and true-catch rates cannot be
computed honestly. The observed unusable scores span 0.086736–1.261598, so a
single blur threshold would also miss several known unusable frames. This
calibration must stop here until the three real-food control groups and a
labelled unusable blur set are collected; the metric remains unshipped.

## Reproduction and scope

**The six rows above are not reproducible from this repository.** They were
measured with `measurePngCaptureQuality` against coordinator-provided files in
`/tmp/mealog-adversarial/`; the image bytes were never committed and that
directory is gone. Committing the six images with a recorded licence, or
recording their SHA-256 and size and re-supplying them, is what would make the
table reproducible and let a reader rerun `measurePngCaptureQuality` against
them. Focused tests cover normalization, the textureless white-frame rule,
deterministic re-encoding, dimensions, and malformed PNG rejection. No
evaluator, golden fixture, baseline, pipeline, runner, gate, response contract,
or scorecard was changed.
