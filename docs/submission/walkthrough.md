# Video walkthrough script — Node/TypeScript submission

Target runtime: **8:40**. This is a timed submission recording script.
Rehearse and re-check every evidence anchor against the recording commit before
the take.

> **Provenance.** August 2026 recording script, kept as historical evidence.
> Its numbers are the full-set run with the licence-restricted Turkish
> catalogue installed (10/80, Item F1 0.15, FP 86.0%, 145 variants), which a
> clean clone cannot reproduce. The current published snapshot is 77 golden
> rows and 38 retrieval variants over `en_US`+`ja_JP`, stated in
> [README → Evidence snapshot](../../README.md#evidence-snapshot) and checked
> by `make claims` (D23).

The walkthrough shows the Node/TypeScript edge and the Expo client. The Python
path appears only as the offline evaluation harness. This is a decision-led
walkthrough: enter a file only to support one boundary, never as a
folder-by-folder code tour.

## Run of show

| Time | Beat | Recording condition |
|---|---|---|
| 0:00–0:40 | Problem, scope, and assumptions | Title card and app shell |
| 0:40–2:20 | Capture, loading, result, portion band, auditability, and routing | Current Node endpoint or deterministic fixture fallback |
| 2:20–2:50 | Live out-of-catalogue abstention | **Required**; use the labelled fixture fallback only if the live shot cannot run |
| 2:50–4:00 | One architecture diagram and the server-action routing table | Node/Nest boundary on screen |
| 4:00–5:20 | The model mistake that changed the design; grounded nutrition, the separate estimate lane, and worst-cuisine measurement | D1/D3/D19/D20 and one short code boundary |
| 5:20–6:00 | EatBetter comparison, bounded to observed public surfaces | Visibility of uncertainty, not accuracy |
| 6:00–6:55 | Offline scorecard, ablation, retrieval, and regression guard | Fresh scorecard from the recording commit |
| 6:55–7:30 | Security and privacy | Request boundary and CI guard |
| 7:30–8:10 | Limitations, exact calorie denominator, and the open photo-count defect | `n=80` scorecard plus #218 status |
| 8:10–8:40 | Error/empty states and next steps | Close on the honest state, not a success animation |

## Recording rules

- Every metric is spoken with its denominator or sample count in the same
  sentence. Do not round a figure up or substitute a historical number.
- The only live-provider evidence named here is the verified 2026-08-23 run on
  `acfa6dd`: 8/8 text scenarios passed and `C7.jpg` returned exactly one
  `tr.ayran`. This is not broad live accuracy and it does not prove visual
  counting of every image.
- Do not show an API key, a personal photograph, a raw provider envelope, or a
  personal identifier. If the device path fails, use the deterministic fixture
  recording and say **fixture / demo path** on screen.
- Rotate the provider key exposed during development before recording. Never
  show a terminal or environment view that could reveal the replacement.
- The abstention at 2:20–2:50 is mandatory. It is the strongest proof that the
  system knows when not to guess.
- Do not say “production ready”. Do not narrate the multi-agent process.

## Script

### 0:00–0:40 — The problem, the scope, the assumptions

**Picture:** Title card, then the mobile capture surface.

**Say:**

> A meal photo is an uncertain observation, but a nutrition log has to be a
> decision someone can inspect. Mealog identifies a catalogue food, shows a
> portion band, and calculates nutrition from the chosen catalogue row.
>
> The delivered runtime is Node and TypeScript behind a NestJS HTTP edge, with
> an Expo client. Python remains the offline evaluator, so measurements replay
> without a provider key. When the catalogue cannot support an identity, the
> correct result is an abstention, not a plausible guess.

**On-screen proof:** the app shell and the Node entrypoint. Do not open a file
tree or read a scorecard in this opening.

### 0:40–2:20 — Capture, loading, result, and auditability

**Picture:** Choose a photo or enter a meal description, then show the loading
state and result. Tap **“Nasıl bulundu?”** to expand the optional audit details.

**Say:**

> I start with the deterministic demo path so the recording does not depend on
> a live key. The same boundary accepts a camera photo, a library photo, or
> text. The loading copy says **“Fotoğrafın işleniyor; öğünün için kanıt
> oluşturuluyor.”** and names the stages: **“Tabak okunuyor”, “Katalogda
> eşleşme aranıyor”, “Porsiyon tahmin ediliyor.”**
>
> The server response decides the next screen. The client never guesses from
> the local prompt. `auto_accept` goes to **Gün**, highlights the record, and
> offers one-tap undo. `review` goes to **Kontrol et** with nothing written;
> if there is a question, it is visible — **“Kaç adet?”**. The server's `ask`
> action is the abstention surface: it shows the observation and next choices
> without creating a record. Degraded stays in Review with a warning and never
> auto-accepts. A `503` is an error-with-retry state ("Sağlayıcıya ulaşılamadı. Taslağın güvende."), not a meal result.
>
> Review shows a band, never a single asserted mass: **“yaklaşık [gram] g
> ([alt]–[üst] g)”**. I open **“Nasıl bulundu?”** when I want the technical
> audit trace: it shows the
> `food_id`, catalogue source, confidence, portion source, provenance, and
> p10–p90 evidence.

**On-screen proof:** loading copy, one result with its portion band, the tap that
opens the audit panel, and the action transition. Do not show raw JSON.

### 2:20–2:50 — Live out-of-catalogue abstention and fallback logging

**Picture:** Mobile capture of an out-of-catalogue food (e.g. `karnıyarık` or `baked beans`).

**Say:**

> When a food is outside the catalogue, Mealog refuses to attach a laboratory
> row or present model output as verified nutrition. The screen acknowledges
> the observation—for example, recognizing karnıyarık—without silently
> converting it into catalogue truth.
>
> In live mode, the separate D19/D20 lane can prepare an **AI estimate —
> unverified** with a range and visible assumptions. It is never auto-accepted,
> requires the user's explicit choice, and is excluded from grounded accuracy
> metrics. The user can instead save an uncaloried note or enter a manual value.
> The “Suggest dish” control is a product-direction prototype; it is not a live
> catalogue-learning system.

**On-screen proof:** The out-of-catalogue screen with recognized dish name,
verified-versus-unverified labelling, estimate range and assumptions if the live
fallback succeeds, honest local logging alternatives, and prototype suggest
control. Keep this segment; do not replace it with another success case.

### 2:50–4:00 — One architecture, and why the route is server-owned

**Picture:** One diagram, then the two boundaries that make the diagram true.

```text
Expo capture or text
        -> POST /v1/meals
        -> NestJS edge
        -> VisionPort (fixture replay or provider)
        -> normalize -> retrieval -> resolve -> portion -> nutrition
        -> MealLog { action, degraded, items, totals }
        -> Day / Review / Add

ABSTAIN + live mode
        -> POST /v1/meals/estimate
        -> unverified range + assumptions
        -> explicit user acceptance or discard
```

**Say:**

> The edge is thin. It validates the request, applies user-scoped idempotency,
> and delegates to a framework-free pipeline. The provider is a port, so the
> runner can use a recorded fixture without booting HTTP. The pipeline
> normalizes observations, retrieves candidates, resolves to a catalogue ID or
> `ABSTAIN`, estimates a p10–p90 band, and computes nutrients deterministically.
> After an abstention, a separate endpoint may prepare an unverified model
> estimate. It does not enter the grounded pipeline, change the server action,
> or save itself.
>
> One contract controls the experience: `action` and `degraded` come from the
> server. A fallback-backed answer is review, never acceptance. A provider
> error is retry, not a saved record. The client does not infer success from a
> local string, confidence, or screen transition.

**On-screen proof:** the diagram, `POST /v1/meals`, and the VisionPort boundary.
Show only enough of each file to support the boundary. Do not scroll through
directories.

### 4:00–5:20 — The wrong model answer, and the product boundary

**Picture:** D1, D3, D19, and D20, then the nutrition boundary.

**Say:**

> Here is the moment the model was wrong. An early vision response supplied a
> plausible calorie number without a catalogue food or measured portion. We
> caught it because it had no inspectable source: the evaluator could not tie it
> to a closed-set identity or reproduce the arithmetic. That was the wrong
> contract, not a number to polish.
>
> In the grounded path, the model observes food surfaces only. Retrieval and
> resolution choose a catalogue `food_id` or return `ABSTAIN`; only nutrition
> produces a number from catalogue data and grams. That remains the first and
> strongest decision.
>
> D19 and D20 add a deliberately weaker product lane after abstention. It may
> return broad model-estimated nutrition ranges and assumptions, labelled
> **AI tahmini — doğrulanmamış**. Generation can be batched for up to 20
> unresolved items, but acceptance and saving are never automatic. These rows
> are excluded from the grounded scorecard and need their own labelled eval.
>
> The second is how to read accuracy. A mean can hide the failing cuisine, so
> the headline is the worst bucket with coverage beside it. Abstention is not a
> zero-calorie answer: it costs coverage, but avoids invented identity and
> nutrition.

**On-screen proof:** D1, D3, D19, and D20; the closed-set resolver; the pure
grounded nutrition boundary; and the unverified estimate badge. Do not show a
made-up provider response or a folder tour.

**Comparison beat — about 40 seconds, at the end of this decisions block.**

**Say:**

> One required comparison, bounded to observed public surfaces. I am not
> inferring EatBetter’s model, catalogue, thresholds, or storage. The
> demonstrable difference is visibility of uncertainty, not accuracy: mealog
> shows a portion band, an audit panel, and a refusal. On the observed EatBetter
> surface I saw no uncertainty signal, so a count error can propagate silently
> into calories, sodium, iron, and glycemic load. On counting, I make no claim in
> either direction. EatBetter was observed on two images: one over-count of
> three against a user-confirmed two, and one correct count of two. mealog was
> observed on one of those images and got it wrong, three runs of three. One
> product has two data points; the other has one.

**On-screen proof:** `comparison.md` (this directory) and the two bounded observation notes.
Do not show an inferred competitor architecture or claim an accuracy winner.

### 6:00–6:55 — Evaluation, ablation, and the regression guard

**Picture:** The scorecard, retrieval table, and local regression check. Generate
the scorecard from the recording commit and keep its SHA-256 visible.

**Say:**

> The current scorecard covers **12%: 10/80** samples. Item F1 is **0.15**, FP
> is **86.0%**, and calorie MAPE is **12.7%**. I will state its exact denominator
> again in the limitations segment; this is not broad live accuracy.
>
> The ablation makes the trade-off visible: V0 ungated is **100% coverage at
> 100% MAPE**; V3 is **12% coverage at 12.7% MAPE**. V3 answers less often
> because it refuses unsupported identities.
>
> Retrieval is a separate guard: across **145 variants**, Recall@1 is **100%**
> and MRR is **1.000**; across **22 negative probes**, there are zero wrong
> accepts. On **10 out-of-catalogue images**, there are **10 correct
> abstentions** and zero false accepts. The regression gate compares buckets,
> not just an aggregate.

**On-screen proof:** scorecard SHA, the V0/V3 rows, the retrieval rows, the
out-of-catalogue result summary, and the passing local regression check. Hosted
Actions currently does not start because of the repository account's billing
state. CI now runs on GitHub-hosted runners, so show the current run from the
branch under review instead of an old screenshot.

### 6:55–7:30 — Security and privacy

**Picture:** The HTTP boundary and the CI secret guard.

**Say:**

> The photo is handled as a bounded request. The edge checks the declared type
> and the bytes themselves before transport. The request bytes live only for
> the provider call; the adapter releases its strong reference afterward. The
> application does not persist the photograph, and a fixture stores observations,
> not the image or raw provider envelope.
>
> The provider key stays in server configuration and never appears in the
> repository or recording. Idempotency is user-scoped, but its optional header
> is not authentication. Health is liveness, not downstream-provider health.

**On-screen proof:** request validation, configuration boundary, and secret-scan
CI result. Never show credentials, a user photo, or a user identifier.

### 7:30–8:10 — Limitations, with the denominator spoken aloud

**Picture:** The scorecard and the two-simit evidence note.

**Say:**

> The scorecard has **n=80** samples, but the calorie MAPE denominator is **TWO
> scorable rows**, not 80: **12.7% over 2 scorable rows**. The other rows do not
> provide trustworthy calorie truth, so they are not zero-calorie errors.
> Coverage is **12%: 10/80**: selective answers and a very small calorie
> denominator.
>
> **Known limitation & quantity disambiguation:** On ambiguous multi-item plates
> like two simits, visual perception may return an unresolved item count; the
> system explicitly asks **“Kaç adet?”** in Review rather than guessing wrong
> calories.

**On-screen proof:** scorecard with `n=80` and `2 scorable rows`, then the
two-simit evidence. Do not hide the denominator in a footnote.

### 8:10–8:40 — Error, empty, and what comes next

**Picture:** The error-with-retry state, then an empty Day state, then the
abstention screen as the closing frame.

**Say:**

> The last two states are also part of the product, not polish. A provider
> failure says **“Bir sorun çıktı.”**, keeps the draft safe, and offers **“Tekrar
> dene”**. A `503` is not a first-class answer: it preserves the draft, creates no record, and lets the user retry. An empty day says
> **“Henüz bir öğün yok.”** and gives one next action.
>
> Record this 8:40 run from the current commit, and send the submission with the
> scorecard hash and stated denominators. End on the abstention: useful because it shows evidence, safe
> because it can say no.

**On-screen proof:** retry button, empty state, and the deliberate abstention.
Do not end on a fabricated success state.

## Final edit checklist

- [ ] Rehearse from a clean checkout after code freeze.
- [ ] Regenerate the scorecard from the recording commit; verify its SHA-256,
      every figure, and every denominator before recording.
- [ ] Keep the 2:20–2:50 live abstention in the final cut; use and label the
      fixture fallback only if the live shot cannot run.
- [ ] Confirm the server action, not a local guess, controls every screen.
- [ ] Confirm degraded results show Review and never auto-accept.
- [ ] Confirm the portion is always spoken and shown as a band.
- [ ] Confirm the current #218 count-clarification behavior and issue status;
      do not call it fixed without merged and runtime evidence from the
      recording commit.
- [ ] Confirm no API key, personal photo, personal identifier, or raw provider
      payload appears in the recording.
- [ ] Rotate the exposed provider key before recording.
- [ ] Clear the GitHub Actions billing/spending blocker and confirm the hosted
      submission-commit run executes and passes; local checks are not a substitute.
- [ ] Confirm the full script is at or under 9:00.
