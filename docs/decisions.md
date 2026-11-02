# Decision log

Format: decision → rejected alternative → constraint → cost.

---

## D1 — The model never produces a nutrient number

**Decision.** The vision/LLM stage returns observed items only. Resolution picks a
`food_id` from a closed candidate set produced by retrieval, or returns `ABSTAIN`.
Nutrition is computed by a pure function over the canonical catalogue.

**Rejected.** Ask the model for calories directly (shipped as the `V0` baseline so
the cost of the alternative is measured rather than asserted).

**Constraint.** The brief's core problem is *canonical* foods. Canonicality requires
an ID space the model cannot invent.

**Cost.** Recall is capped by catalogue coverage: a food that is not in a locale pack
cannot be logged, only abstained on. Mitigated by the ask-flow and a
"suggest a new food" path. This is a real limitation, not a rounding error —
`E3` (hallucination) is traded for `E4` (miss), and a miss is the cheaper error
because the user can see it.

---

## D2 — A locale is a data pack, not code

**Decision.** Each market is a directory: `foods.jsonl`, `aliases.jsonl`,
`units.jsonl`, `text_rules.yaml`, `pack.yaml` (with a **license** field). Nothing
in `server/src` references a locale by name. Three packs are defined (`en_US`,
`tr`, `ja_JP`) plus `scripts/build_locale_pack.py`. `en_US` and `ja_JP` ship in
full; `tr` ships metadata only, because its rows are `restricted-noncommercial`
and are installed separately with `scripts/install_restricted_pack.py` (D15).

**Rejected.** One global catalogue with per-market special cases.

**Constraint.** The company is expanding beyond its current market. What matters is
not "does it know Turkish food" but "what does market N+1 cost". Three packs exist
because an abstraction with one implementation is ceremony; with three it is a seam.

**Cost.** Duplication across packs (rice appears in all three with different IDs and
different source values). Accepted: per-market provenance and licensing beat
deduplication, because the packs have different legal terms. `tr` uses TURKOMP,
which carries commercial-use restrictions — recorded in `pack.yaml` rather than
discovered later.

---

## D3 — Headline metric is the worst cuisine, and accuracy is read with coverage

**Decision.** The scorecard leads with worst-bucket MAPE and the worst-to-best
spread. Calorie error is computed over **covered** samples only, with coverage
reported beside it. CI fails if *any* cuisine bucket regresses.

**Rejected.** A single aggregate MAPE.

**Constraint.** Averaging hides distribution shift, which is the exact failure this
project targets. And scoring a deferred meal as a zero-calorie answer punishes the
system for correctly declining to guess — the first harness run did precisely that
and inverted V3's result, which is why the harness was built before the model.

**Cost.** More numbers to read, and small per-bucket `n` means wide intervals.
Reported honestly rather than smoothed away.

---

## D4 — Offline-reproducible evaluation via recorded fixtures

**Decision.** `make eval` replays recorded provider responses. No key, no network,
no spend. `make eval-live` hits the real provider and re-records.

**Rejected.** Require an API key to reproduce results.

**Constraint.** The most common take-home failure is "the reviewer could not run
it", and the most common criticism of AI submissions is unverifiable numbers. This
closes both with one mechanism.

**Cost.** Fixtures drift from the live provider. Mitigated by stamping every fixture
with provider and `prompt_version`, and re-recording whenever either changes.

---

## D5 — Photo ingress uses bounded multipart and content-hash fixture keys

**Decision.** `POST /v1/meals` accepts `multipart/form-data` with an `image`
part, validates an allow-list of image MIME types, and caps the image at 10 MiB.
The request body is held in memory only for the provider call; the application
does not persist the photograph. `VisionPort` receives a `VisionInput`; fixture
replay keys image inputs by SHA-256 and retains `sample_id` only as a fixture-
provider compatibility path.

**Rejected.** Base64 JSON would avoid a multipart parser but expands every image
by roughly one third and makes the mobile upload path less suitable. A
pre-signed object URL would avoid keeping bytes in the API process but requires
an object store, expiry policy and cleanup worker that do not exist in this
take-home.

**Constraint.** The photo path must be a real input boundary before a mobile
client is built, while D4 requires offline fixture replay with no image upload
or provider key.

**Cost.** Multipart adds one runtime dependency and the API process briefly
holds image bytes. Provider-side retention and processing are governed by the
provider's terms; this repository records only validated observations, never
the photograph or response envelope.

---

## D6 — Retrieval scores coverage, not similarity

**Decision.** Two signals over the same documents — word 1–2 grams and character
3–5 grams — blended by weight, each scored as **IDF-weighted asymmetric
coverage**: *how much of what the user said is accounted for by this food's
surface forms, weighted by how distinctive each piece is.* Exact surface hits
outrank fuzzy ones. A known confusion surfaces its target capped below the
accept threshold, so the resolver abstains and the gate asks.

**Rejected.** *BM25* — canonical food names are 2–6 tokens, so document-length
normalisation has nothing to normalise, and it costs a dependency. *Reciprocal
Rank Fusion* — it exists to merge ranked lists whose scores are not comparable;
both signals here are already comparable on the same documents, and RRF would
leave a rank-derived number `resolve.py` could no longer threshold as a
confidence. *Cosine similarity* — symmetric, so a short query is penalised for
everything an alias-rich document contains that the user did not say. `pilav`
scored 0.28 against `sade pirinc pilavi` purely because the document was longer;
ranking survived that, the accept threshold did not.

**Constraint.** `resolve.py` thresholds on the absolute score, so the score has
to stay readable as a confidence. Turkish and Japanese make inflection and
transliteration the common case rather than the edge case.

**Cost.** Coverage is not a similarity: two foods can both score high on a short
ambiguous query. That is genuine ambiguity, handed to the margin rule instead of
resolved silently. And unseen n-grams must be charged at maximum IDF or a
foreign dish scores against a local one — `pizza margherita` matched a Turkish
rice dish at 0.55 before that correction, because every n-gram that made it
*pizza* had been silently dropped by the vectoriser.

---

## D7 — Portion is a distribution, and density belongs to the food

**Decision.** Portion returns `(grams, p10, p90)`. Interval width is graded by
evidence: a stated quantity with a known unit is narrow, an assumed quantity
falls back to the catalogue-default band, and an unknown density widens further
around a declared midpoint. **Volume units carry volume only.**

**Rejected.** *A point estimate* — mass error dominates calorie error, and both
the confidence gate and the UI need the width. *Density on the unit* — tried and
reverted within the same pull request. A cup is not made of rice; borrowing one
food's density made every other food measured in cups **worse** than the 1 g/ml
assumption it replaced.

**Constraint.** Our own taxonomy names `E8` (unit/density error) and the code was
committing it. A guess must never be presented with the confidence of a
measurement.

**Cost.** Every volume unit currently falls to the unknown-density band
(0.45–1.75), which is wide. Once the gate reads the interval, coverage drops on
volume-measured meals — that is the system telling the truth, not a regression.
The fix is `density_g_per_ml` on `CanonicalFood`, which narrows the band with
evidence rather than with optimism.

---

## D8 — One component fine-tuned, one specified and not trained

**Decision.** The frontier VLM is **rented, not fine-tuned**. The component we
train is a locale adapter that aligns images into the canonical food embedding
space, on a mixed multi-cuisine corpus, reported per cuisine. A mass regressor on
Nutrition5k is **specified in full and not trained**.

**Rejected.** Fine-tuning the frontier VLM for general food recognition.
Published benchmarking on Nutrition5k puts Gemini 3.0 Flash at 80.7 kcal MAE /
CCC 0.767, and finds that low-data fine-tuning on strong base models yields
limited gains without large, high-quality corpora. In six days that produces a
model that loses to the baseline and a story about trying.

**Constraint.** Fine-tuning is optional in scope and the question is
which path was chosen and why. Measuring *where* the frontier is weak has to come
before training anything: identification is adequate, mass is not, and local
cuisine is not.

**Cost.** **Nothing is trained yet** — see
[`docs/submission/STATUS.md`](submission/STATUS.md). This entry records a
decision, not a result, and it is being misread the moment it is taken for one.
The same published work found that human annotators corrected label omissions in
Nutrition5k and moved measured ingredient overlap from 0.62 to 0.82, so a naive
fine-tune on those labels would learn the dataset's errors and report them as
accuracy.

---

## D9 — Mobile is Expo / React Native, demoable without a key

**Decision.** Expo + React Native + TypeScript. Three screens. Fully demoable
against recorded fixtures with `VISION_PROVIDER=fixture`.

**Rejected.** *Native* — two codebases in six days. *Flutter* — no advantage
here and further from the stack this team most likely runs. *A web app* — the
brief calls that a format violation, not a shortcut.

**Constraint.** A reviewer has to be able to run it. A QR code and Expo Go is the
shortest path from clone to a phone, and "could not run it" is the most common
reason a take-home is rejected. The demo also cannot depend on an API key,
because D4 already promises the numbers reproduce without one.

**Cost.** Expo Go constrains native modules. Nothing this app needs sits outside
it — camera and multipart upload are both covered — but if that ever changes,
EAS build is the escape hatch and it is slower.

---

## D10 — Record the golden set with Flash-Lite, retain a full-Flash comparison strip

**Decision.** Record the complete golden set with `gemini-flash-lite-latest`.
Keep full Flash for a 12–15-sample comparison strip rather than using it for
every recording. This fits the free-tier recording path while preserving a
direct comparison against the stronger model.

**Rejected.** A paid tier — the spend is not justified for recording the full
set. Shrinking the set — it would discard cuisine and coverage evidence rather
than solve the throughput constraint.

**Constraint.** The golden set must remain complete and re-recordable without
paid-provider access. The comparison strip must be large enough to expose a
model difference, while the free tier's full-Flash allowance is 20 requests per
day.

**Cost.** Lite becomes the model behind the complete recorded set, so its
results are not interchangeable with full Flash. A 12–15-sample strip cannot
establish full-set parity, and free-tier quota makes a complete refresh slower.

---

## D11 — Portion-uncertainty gate is specified, measured, and deliberately not shipped

**Decision.** Specify and measure the portion-uncertainty confidence gate, but do
not ship it yet. On the nine-sample synthetic seed, the gate would keep four
samples at 13.0% MAPE and newly withhold three at 8.8% MAPE; two samples were
already withheld by retrieval. The gate therefore withholds better answers on
this seed — it is abstaining blind, not demonstrating selective risk reduction.
This risk-coverage measurement is recorded in [PR #39](https://github.com/zexy2/mealog/pull/39).

**Rejected.** Ship the current gate as a proven risk-control — its seeded
operating point drops V3 coverage from 78% to 44% and raises covered mean MAPE
from 11.2% to 13.0%. Tune its thresholds against the nine synthetic fixtures —
that would turn seeded priors into a production claim.

**Constraint.** D3 requires coverage and error to be read together, and D7
requires portion uncertainty to remain visible rather than silently accepted.
The gate must show selectivity on real provider fixtures before it changes the
runtime operating point; `AUTO_ACCEPT` and `ASK_BELOW` remain untouched until
then.

**Cost.** The gate remains specified and measured but unavailable in the shipped
runtime. Current coverage is preserved at the cost of accepting some answers the
future gate may withhold; real provider fixtures and density evidence are
required before this decision can be revisited.

---

## D12 — Node.js + TypeScript backend, NestJS edge, Python eval harness

**Decision.** The backend is Node.js and TypeScript. NestJS sits at the edge only
— controllers and providers. `src/domain/` and `src/pipeline/` carry no framework
imports, enforced by an invariant in `scripts/check_invariants.py` that was
broken deliberately, in both the `import` and `require` forms, to prove it fires.
That boundary is what lets the evaluation harness import the same modules the API
serves without booting the framework. The harness therefore **stays in Python**
and drives the pipeline through an eval CLI exposed by the TypeScript side; the
README states plainly that it is offline research tooling and that the delivered
service is Node/TypeScript. The port is gated on parity: the scoring code does not
change, so the same recorded fixtures must produce the same scorecard with the
pipeline as the only variable. The Python serving path is deleted only after
parity passes. The 249 Python tests are not transcribed; roughly eight to twelve
behaviours move across, among them the abstention threshold, refusal to resolve a
food outside the catalogue, numeric equality of the deterministic nutrition
function, the empty-vision path, and the regression guard firing on a threshold
breach.

**Rejected.** *Fastify.* This was not rejected once but twice, and the second time
is the one worth recording. Mid-port the choice was reopened on the argument that
NestJS module and decorator ceremony is a poor risk four days from submission,
because the property that cannot be compensated for is the repository starting
from a clean clone. It was closed again on measurement rather than preference:
the scaffold installs, builds, lints and tests from a clean clone with an empty
npm cache in seconds on the pinned Node version, boots over HTTP, and the
framework is fenced out of the pure core by an invariant demonstrated to fail
the build. The risk the alternative existed to avoid had already been measured
away, and rewriting would have spent critical-path time removing a hazard that
was no longer there. *Porting the harness as well* — roughly a day for close to
no additional signal, and it would have changed the scoring code and the
pipeline at the same time, leaving the parity comparison with two variables
instead of one. *Staying on Python* — the brief says "Do not use ... or other
backend stacks" and names stack fit rather than technical merit as the reason,
so a merit argument does not answer it. *A thin TypeScript proxy in front of the
Python pipeline* — satisfies the letter and fails the intent, since the logic
under evaluation would still be Python.

**Constraint.** `scikit-learn` has no Node equivalent worth depending on. The
word and character TF-IDF vectorisers and the IDF-weighted asymmetric coverage
score are implemented in-house. Only the vectoriser is new code; the scoring
layer was already custom (D6). Domain field names stay snake_case across the
port, because those objects cross the API and fixture boundary where the wire
shape is the contract, and a rename would read as a diff at the parity gate.

**Cost.** Two languages remain in the repository, and that has to be justified in
the README rather than left for a reviewer to notice — an unexplained second
language reads as redefining the brief in silence. The edge layer carries
decorator and dependency-injection ceremony a smaller framework would not
require; the invariant confines it but does not remove it. D7's portion
distribution remains visible across the boundary, and D11's confidence gate
stays parked. In exchange the parity gate turns the boundary claims in D1, D2
and D6 into a demonstrated property: the served pipeline changes language and
the measured numbers do not move.

---

## D13 — Privacy-by-Design: Edge/Server-side EXIF scrubbing, face blurring, and ephemeral retention

**Decision.** All images processed by MeaLog undergo Edge/Server-side EXIF/geotag scrubbing and sanitization before vision model ingestion (`sanitizeImageBuffer()`), automatic face/PII detection & blurring, and strict ephemeral in-memory processing with zero persistent photo retention.

**Rejected.** Storing user meal photos on disk/cloud for training or fine-tuning without explicit opt-in consent. Passing raw device EXIF headers (timestamp, GPS coordinates, camera serial) to external vision providers.

**Constraint.** GDPR and KVKK compliance require minimizing personal identifiable information (PII). Photos containing dining companions, restaurant staff, or background documents must not leak identifiable biometrics to third-party LLM providers.

**Cost.** Face blurring and EXIF sanitization introduce a lightweight pre-processing step (~10-20ms) and require privacy invariants to be verified in pipeline tests (`test/face_blurring.test.ts`, `test/pipeline.privacy.test.ts`).

---

## D14 — Privacy Pipeline Boundary: Deterministic Edge EXIF Sanitization vs. Standalone RGBA Face Blurring

**Decision.** The edge service's active HTTP ingestion pipeline deterministically executes byte-level EXIF/GPS/metadata stripping (`sanitizeImageBuffer()`), text PII redaction (`sanitizePiiText()`), and adversarial prompt injection filtering (`sanitizePromptInput()`). Pixel-level face detection and mosaic blurring (`blurFacesInPixelArray`) is maintained and tested as a pure-TypeScript algorithm operating on raw RGBA pixel arrays, decoupled from the live edge controller.

**Supersedes.** Clarifies the execution boundary stated in [D13](#d13--privacy-by-design-edgeserver-side-exif-scrubbing-face-blurring-and-ephemeral-retention).

**Rejected.** Ingesting native C++ image decoding/encoding bindings (e.g. `sharp`, `libvips`, `canvas`) into the edge server container. While native libraries would enable on-the-fly JPEG decoding/re-encoding for face blurring in the HTTP thread, they introduce significant Docker image bloat, compilation friction on Alpine Linux, and CPU latency spikes under high request concurrency.

**Constraint.** The edge container must install and build cleanly with zero native compilation dependencies across macOS, Linux, and Alpine Docker.

**Cost.** Compressed image payloads sent to the live vision provider have EXIF/GPS stripped but rely on upstream provider privacy commitments or client-side camera canvas blurring for uncompressed biometric masking.

---

## D15 — Audited Data Loop: Abstention as a Measurable Feedback Queue over Unverifiable Self-Training

**Decision.** The ABSTAIN state is a first-class architectural boundary that converts catalogue gaps into an auditable telemetry feedback queue rather than treating gaps as unrecoverable errors or asking LLMs to hallucinate unverified calories. When a recognized dish falls outside the closed locale pack, the system provides two honest logging alternatives: (1) logging as an uncaloried meal note (`portion_provenance: "uncaloried_note"`, excluded from daily calorie/macro totals), and (2) logging with an explicit user-entered calorie estimate (`portion_provenance: "manual_user_input"`). New food items enter the closed catalogue only via human nutrition curation, licensed laboratory data verification (TÜRKOMP/USDA), and regression-gated locale pack releases.

**Rejected.** *Self-training from raw user text corrections.* User corrections are not ground truth: they lack standard recipes, preparation methods, cooking fat amounts, and nutritional licenses. Ingesting user recipes automatically introduces data poisoning, variance, and violates D1. *Prompt-based calorie estimation on unmapped dishes* — asking an LLM to guess calories for out-of-catalogue dishes hallucinates unverifiable numbers and breaches D1.

**Constraint.** D1's zero-hallucination guarantee is non-negotiable. Nutrient calculations must remain 100% deterministic and sourced from verified laboratory composition rows.

**Cost.** Expanding catalogue coverage requires a curated release cycle rather than instant automated ingestion. In exchange, the system guarantees 100% auditable provenance for every calorie presented to users.

---

## D16 — Implementation Boundary: Client-Side Fallback Logging vs. Production Curation Queue

**Decision.** Clarify the implementation boundary of the Audited Data Loop stated in [D15](#d15--audited-data-loop-abstention-as-a-measurable-feedback-queue-over-unverifiable-self-training). In the delivered prototype:
1. **Shipped Client Functionality:** Two honest local logging paths for out-of-catalogue dishes:
   - Uncaloried meal notes stored in device storage (`portion_provenance: "uncaloried_note"`, displayed as `— kcal (Not)`, excluded from daily caloric totals).
   - User-entered manual calorie logs stored in device storage (`portion_provenance: "manual_user_input"`, displayed with `(Manuel)` tag).
   These records are strictly client-side device logs; they never claim server-side verified nutrition calculation.
2. **Product Direction Prototype:** The "Yemeği Kataloğa Öner" UI control demonstrates the user experience flow for requesting catalogue additions. It is explicitly positioned as a product direction prototype, without claiming an active server-side telemetry aggregation database in this submission.
3. **Production Architecture:** Production deployment specifies a rate-limited telemetry ingestion endpoint, anonymized frequency aggregation, a nutritionist curation portal, and regression-gated locale pack releases.

**Supersedes.** Clarifies the shipped boundary of [D15](#d15--audited-data-loop-abstention-as-a-measurable-feedback-queue-over-unverifiable-self-training).

**Rejected.** Claiming a live server-side curation queue exists when the current submission implements client-side state.

**Constraint.** Claims in presentation and documentation must be defensible: no prototype capability is described as production infrastructure.

**Cost.** The boundary between prototype UX and production infrastructure is explicitly documented rather than left ambiguous.



---

## D17 — Portion uncertainty gate is shipped and active

**Decision.** The portion-uncertainty gate (`portionConfidence`) is explicitly enabled in the TypeScript pipeline (`effectiveConfidence`). A meal whose portion cannot be resolved to a confident narrow interval (e.g. unknown density, stacked items) is gated from `AUTO_ACCEPT` and routed to `review` or `ask`.

**Supersedes.** D11, which deliberately parked the gate.

**Rejected.** Reverting the codebase to match D11 and hiding portion uncertainty from the confidence routing. The gate is a core safety mechanism that prevents silent massive calorie errors caused by visual miscounts or density assumptions.

**Constraint.** Auto-accepting a meal with a 200+ kcal uncertainty interval violates the product's trust boundary. The UI must ask the user for confirmation when the visual evidence is insufficient to count or size the food.

**Cost.** The measured `AUTO_ACCEPT` rate on the offline golden set drops (to 0 on the 80 samples), increasing user friction by requiring a tap in the Review screen. This is an explicit trade-off: safety and explicit confirmation over frictionless but potentially wrong logging.

---

## D18 — Correction telemetry ships as a privacy-minimized local prototype, not an automated learning system

**Decision.** Supersede D16's statement that no server-side telemetry endpoint
ships. The delivered mobile client sends review events to the same configured
API base URL as meal requests, and `POST /v1/telemetry/events` appends them to a
process-local JSONL store. The endpoint requires `X-User-Id` for rate limiting
but does not persist it. Before disk append, the server replaces the raw
idempotency key with a SHA-256 request hash and redacts supported PII patterns
from free-text fields. Photos and provider envelopes are not telemetry fields.
The operator-run curation script is shipped; automatic training, a dietitian
portal, shadow traffic, and model promotion are not.

**Rejected.** Hard-code telemetry to mobile `localhost`; persist raw request
keys or unredacted correction text; describe a local JSONL file and curation
script as an enterprise lakehouse or completed active-learning flywheel.

**Constraint.** Corrections are signals, not licensed nutrition ground truth.
D1 still forbids telemetry from producing nutrients or silently changing a
locale pack, golden label, threshold, or model. Repository documentation must
separate shipped behavior from proposed production architecture.

**Cost.** The prototype store is process-local, non-durable across container
replacement, and unsuitable for multi-instance delivery. Because no user ID is
stored, an individual anonymized event cannot be selected by the current GDPR
delete endpoint. Production telemetry therefore needs authenticated
pseudonymous ownership, retention limits, deletion semantics, durable storage,
and explicit human curation before it can support learning claims.

---

## D19 — Unverified LLM nutrition is a separate product lane, never grounded truth

**Decision.** Supersede D1 and D15 only for an explicit, user-requested fallback
after closed-set resolution returns `ABSTAIN`. A separate server endpoint may ask
the configured Gemini model for broad calorie and macro ranges plus stated
assumptions. The response is always labelled `llm_unverified_estimate`, requires
an explicit user action, never uses `auto_accept`, and never claims catalogue,
TÜRKOMP, laboratory, or measured provenance. Grounded V1–V3 evaluation and the
canonical nutrition pipeline remain unchanged.

**Rejected.** Client-side hardcoded calorie defaults; placing a provider key in
Expo; silently mixing an LLM midpoint into a catalogue result; presenting a
single precise number without its range and assumptions; treating the fallback
as evidence that grounded meal-logging accuracy improved.

**Constraint.** The UI must distinguish verified catalogue nutrition from an
unverified model estimate at every review and saved-meal surface. Provider
failure returns no numeric fallback. Server validation bounds every returned
range, and catalogue misses remain unresolved until the user explicitly accepts
the estimate or chooses another honest logging path.

**Cost.** The zero-model-nutrients claim no longer applies to the whole product;
it applies only to the grounded pipeline. Accepted estimates can still be wrong,
especially when cooking fat, recipe, and portion are visually ambiguous. They
consume provider quota and are excluded from grounded eval metrics, so their
accuracy requires a separate labelled dataset before any quality claim.

---

## D20 — Prepare unresolved-item estimates as one bounded batch

**Decision.** Supersede D19's tap-per-item request interaction. When Review or
the abstention screen opens in live mode, prepare estimates for up to 20
unresolved items in one Gemini request. Generation is automatic; acceptance and
saving are not. Every estimate keeps the D19 ranges, assumptions, model id, and
`llm_unverified_estimate` label. Catalogue-backed items remain visibly
`Doğrulanmış`; model-only items remain visibly `AI tahmini · doğrulanmamış`.

**Rejected.** One provider call per unresolved item; silently accepting every
generated midpoint; removing unresolved items above an arbitrary five-item UI
cap; unlimited automatic requests; falling back to hardcoded numbers when quota
or provider calls fail.

**Constraint.** One batch contains 1–20 items. New batches require a user-scoped
idempotency key and pass both five-batches-per-minute and twenty-batches-per-day
in-process quotas. Identical retries reuse an LRU cache, concurrent duplicates
share one promise, provider calls time out after 20 seconds, and three
consecutive provider failures open a 60-second circuit. Provider failure or
quota exhaustion returns no nutrition numbers.

**Cost.** Opening a live unresolved-result screen now spends provider quota
without an extra tap. In-memory cache, quotas, and circuit state are per process,
so production needs a shared store and atomic distributed limits. A 20-item
response is slower and harder for the model to keep aligned; request indexes and
strict response-count validation reject partial or reordered ambiguity instead
of guessing.

---

## D21 — Restricted catalogue data is installed, not committed

**Decision.** A pack whose data licence forbids unlimited redistribution ships
as a *definition*: `pack.yaml`, `text_rules.yaml`, and a notice stating the
terms. Its catalogue (`foods.jsonl`, `aliases.jsonl`, `units.jsonl`) is listed
in `.gitignore` and installed with `scripts/install_restricted_pack.py`, which
accepts a directory, a `.zip`, or an HTTPS URL and validates before writing.
Both loaders raise `PackUnavailableError` for a defined pack with no catalogue,
and the API answers `503` with the locale and reason. The licence check
(`make licence`) is blocking, and `status.py` counts committed catalogue files
so the generated status file cannot drift with a developer's local install.

**Rejected.** Committing the rows under a footnote that excludes them from MIT
(the previous state: every clone received restricted data while the licence said
it did not); making the check advisory until the pack "is served from a download
at runtime" (a plan, not a control); deleting the rows and the pack, which would
silently remove the market the project is built around.

**Constraint.** D1 caps recall by catalogue coverage, and the Turkish pack is
the deepest stratum of the evaluation. The data therefore has to stay usable
for anyone entitled to it, while a clone of the repository must not be a
distribution channel for it. The check also has to survive the honest fact that
a deleted blob stays reachable in history, which is why the guard lives in the
build rather than in a review checklist.

**Cost.** A clean clone defines three locales but serves two; the Turkish
demo path needs one install step, and 164 Python / 73 TypeScript tests skip with
a named reason until it is done. The pack's evaluation numbers (the Turkish
retrieval variants and the three Turkish golden samples) are absent from a
clean-clone run, so a reader who wants them must install the data first. That is
the intended trade: absent and named, rather than silent and zero.

---

## D22 — The client has no nutrition table; it asks the catalogue

**Decision.** A typed food name is resolved by the server at
`POST /v1/foods/resolve`. The endpoint runs the same normalization, retrieval
and closed-set resolution the photo path runs, and answers with either a
catalogue `food_id`, a portion range and server-computed nutrition, or an
abstention with zero nutrients and no name. The mobile client holds no
per-100g values, no `food_id` list, and no substring-to-food rules; a TypeScript
test fails the build if one comes back. The only client-side number left is a
calorie the user typed, which is labelled `manual_user_input`.

**Rejected.** Keeping the client table as a "fallback when the server is slow"
(the previous state): it answered `burger` with `tr.kofte_izgara` at 350 kcal,
a row the catalogue does not contain, labelled `source_database: TURKOMP`. It
was not a fallback for a missing server capability — the server answers these
queries correctly from the real pack — it was a second, worse implementation of
one.

**Constraint.** D1 says a nutrient number never originates in a model. It says
nothing about the client, which is how a screen-local table survived several
passes of review: the invariant check reads the server. The rule is the same for
every edge — perception may describe, the catalogue may decide, and a user may
type their own number — so the check had to move to where the violation was.

**Cost.** Adding a food to a plate now needs a round trip, so the plate form has
a loading state and a failure state it did not have before. Offline demo mode
answers from `src/demoResolve.ts`, a short fixed demo catalogue whose provenance
is `DEMO`: it makes the demo coherent without pretending to be the catalogue,
and it is the one place a demo can still be wrong in the same way the real
catalogue is right.

---

## D23 — The published snapshot is what a clean clone reproduces

**Decision.** The numbers in the README's evidence snapshot are defined as the
result of the two evaluations on a clean clone, and they are machine-checked.
`eval/locale_scope.py` excludes any locale whose `pack.yaml` declares
`restricted-noncommercial` from every published denominator; the harness, the
retrieval evaluation and the error decomposition all take their scope from that
one module. `--include-restricted` adds the pack back for a local measurement,
and `make eval-restricted` writes those scorecards, but those numbers are not
published. Both evaluations emit `--summary-json`, and
`scripts/check_readme_claims.py` (`make claims`, also a CI step) parses the
README section and fails with the exact replacement text when prose and
measurement disagree. It also rejects a self-contradictory summary
(`commit + ask > rows`, `scored > eligible`), because otherwise a typo in the
harness and a typo in the README could agree with each other.

**Rejected.** Keep publishing the full 80-row run and let CI skip the claim
check when the Turkish catalogue is absent. That preserves the better-looking
numbers and the project's earlier narrative, but it publishes a claim the
repository's own tree cannot reproduce: on a fresh checkout the same command
reports different coverage and F1, and `eval/retrieval_eval.py` raised
`PackUnavailableError` instead of producing a scorecard. A reader who follows
the README would conclude either that the numbers are invented or that the
project does not run. Skipping the check in CI would have converted that into a
permanent, invisible exemption.

**Constraint.** D21 and D15 put the Turkish rows behind `make pack` because
their licence is noncommercial and the repository is MIT. Once the data is not
in the tree, any metric that depends on it is not reproducible from the tree.
The choice is therefore not whether to scope, but whether to say so and check
it. Counting the excluded rows from the manifests (which do ship) keeps the
size of the gap visible without installing the data that creates it.

**Cost.** The published headline gets worse: coverage 12% → 9%, Item F1
0.15 → 0.13, FP rate 86.0% → 88.2%, and retrieval drops from 145 variants to 38
(30 positives, 8 negatives). Three golden rows and 107 retrieval variants are
named but not measured in the published set, and a maintainer must run
`make eval-restricted` to see the complete picture. That is the intended
trade: the project's least flattering numbers are now its most tightly checked
claim, and the gap between what is measured and what is published is stated in
the same paragraph rather than hidden in a setup step.
