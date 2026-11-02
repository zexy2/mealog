# Mealog compared with EatBetter

> **Provenance.** This is the August 2026 submission comparison, kept as a
> record of what was submitted. Its numbers are the **full-set** run with the
> licence-restricted Turkish catalogue installed, which a clean clone cannot
> reproduce. The current published snapshot is 77 golden rows and 38 retrieval
> variants over the redistributable packs, is stated in
> [README → Evidence snapshot](../../README.md#evidence-snapshot), and is checked
> by `make claims` (D23). Read the numbers below as the historical submission
> state, not as the repository's current claim.

This is a bounded product comparison, not a claim that Mealog beats EatBetter
overall. EatBetter evidence is limited to its
[public App Store listing](https://apps.apple.com/us/app/eatbetter-ai-food-journal/id6639614109)
and directly observed public product surfaces. Nothing here infers EatBetter's
model, catalogue, storage, confidence thresholds or retry architecture.

Each section answers four questions: what is better, why, how it is measured,
and which repository example demonstrates it.

## 1. Closed-set resolution and `ABSTAIN`

**What is better.** The grounded Mealog resolver returns a canonical catalogue
`food_id` or `ABSTAIN`; it does not generate a new food ID.

**Why it is better.** An unsupported dish stays visibly unresolved instead of
quietly inheriting a plausible neighbour's nutrition. The cost is lower
automatic coverage and more correction work.

**How it is measured.** The August full-set retrieval set had **145 variants**:
**122 positive** and **23 negative/confusion** rows. Positive Recall@1 and
Recall@5 were **122/122 (100.0%)**, MRR **1.000**, and deliberately absent
inputs produced **0/22 false accepts**. The current published snapshot has
**38 variants**, 30/30 positive Recall@1, MRR **1.000**, and 0/8 false accepts
on absent rows. Resolution tests separately assert that unknown inputs cannot
escape the closed set.

**Example.** The `baked beans` negative case must not become Turkish
`tr.kuru_fasulye`. The nearest neighbour may be shown for review, but resolution
abstains.

## 2. Abstention instead of silent wrong logging

**What is better.** Mealog makes deferral a designed user state. EatBetter's
public surface emphasizes photo-first logging and feedback; this comparison is
about Mealog's demonstrable safety behavior, not an assertion that EatBetter has
no equivalent gate.

**Why it is better.** A wrong complete-looking log is harder to detect than a
question. Deferral protects the saved diary at the cost of friction.

**How it is measured.** On the August full-set recorded **n=80** V3 replay,
Mealog commits **10/80** meals and routes **70/80** to `ask`, for **12%**
grounded coverage after integer formatting. The current published snapshot
commits **7/77** and asks **70/77**, for **9%**. `ask` includes several
safe-deferral causes; it is not synonymous with 70 catalogue misses.

**Example.** `jp_0002` contains three foods absent from `ja_JP`; all three
resolve to `ABSTAIN` and the meal asks instead of saving a nearest catalogue row.

## 3. Portion uncertainty as p10-p90

**What is better.** Mealog returns `grams` with `grams_p10` and `grams_p90`,
plus portion source and provenance, instead of presenting an unexplained point.

**Why it is better.** Portion error directly changes calories. A visible band
shows when count, density or serving evidence is weak and gives the confidence
gate something measurable to act on.

**How it is measured.** Portion tests cover explicit units, known and unknown
density, packaged serving evidence, catalogue fallback, count origin and
provenance. The TypeScript gate uses the weaker of identity, portion and count
confidence; missing count cannot auto-accept.

**Example.** `pkg_0001` uses a 170 g serving with a **153-187 g** band and Open
Food Facts serving provenance. A catalogue-default portion remains wider and
routes to review when its effective confidence is insufficient.

## 4. Worst-cuisine reporting, not only a mean

**What is better.** Mealog reports worst-cuisine calorie error beside the mean,
coverage and eligible denominator.

**Why it is better.** A strong majority bucket can hide a weak market. The worst
bucket makes that failure visible and prevents an overall mean from becoming a
marketing number.

**How it is measured.** The August full-set V3 replay reports worst and mean
calorie MAPE of **12.7%**, but only over **2/2 eligible and covered rows**. Item
F1 is **0.15** and the reported false-positive rate is **86.0%** across all 80
samples. The small calorie denominator is part of the result, not a footnote.

**Example.** Cuisine rows with no complete, covered calorie truth display an
em dash rather than a fabricated zero. The result therefore says both “12.7% on
two rows” and “not enough evidence for broad calorie accuracy.”

## 5. Auditable identity, alternatives, confidence and mass

**What is better.** A resolved item carries its canonical `food_id`, ranked
candidates, identity confidence, grams and p10-p90 band, catalogue source,
portion source and provenance.

**Why it is better.** The user or reviewer can challenge the identity and mass
that produced nutrition. EatBetter's public workflow is referenced only for its
visible scan/edit positioning; its internal result schema is unknown.

**How it is measured.** The typed `ResolvedItem` contract crosses pipeline, API
and mobile review tests. Current locale packs contain **103/103** rows with a
non-empty food source across three packs; pack-level licence status is checked
separately.

**Example.** The `pkg_0001` trace resolves `us.yogurt_greek_plain` with candidate
score **0.939**, identity confidence **0.963**, 170 g, 153-187 g, USDA catalogue
source and `dataset=Open Food Facts; record_id=0011110107176;
field=serving_size` portion provenance.

## 6. User-scoped idempotency

**What is better.** The same idempotency key replays one result for one user;
the same key from another user is a distinct request.

**Why it is better.** Mobile retries should not duplicate a meal, while two
users must never share cached results. This is a measured Mealog property; no
EatBetter retry behavior is inferred.

**How it is measured.** NestJS end-to-end tests cover identical replay,
conflicting payload rejection, multipart retry, rate-limit interaction and a
cross-user pair. The current cache is bounded and process-local, not distributed
production storage.

**Example.** `shared-key` sent by `user-a` and `user-b` executes as two distinct
requests. Repeating one user's identical request returns the original response
without another pipeline execution.

## 7. Nutrition provenance and licence enforcement

**What is better.** Grounded nutrition comes from canonical rows with a source,
and every locale pack declares a licence status enforced at load time.

**Why it is better.** Legal provenance is part of serving behavior, not a label
added after calculation. Unknown or restricted rights can fail closed.

**How it is measured.** The tree has **103/103** sourced rows in three packs.
`en_US` is public-domain; `tr` is restricted-noncommercial; `ja_JP` is
unverified. Commercial mode permits the first and rejects the latter two.
Locale-pack tests cover known vocabulary, cache bypass and unknown-licence
failure.

**Example.** `load("tr", commercial_mode=True)` raises
`RestrictedPackError`, while `en_US` loads. This test requires no provider call.

## 8. Where EatBetter is better: catalogue and long-tail breadth

**What is better.** EatBetter's public positioning presents broad, convenient
photo logging. Mealog has only **103 canonical foods** across three packs and
must ask outside them. A public EatBetter catalogue count is unavailable, so no
invented head-to-head count is presented.

**Why it is better.** Breadth reduces correction friction. Mealog's closed-set
safety boundary does not compensate the user for a missing common dish.

**How it is measured.** Mealog counts pack rows and reports coverage and
false-accept behavior. The Turkish pack has **57 rows**. Direct inspection shows
common gaps including döner, poğaça, börek, pide and kebap. Köfte is not listed
as a gap because `tr.kofte_izgara` exists.

**Example.** A long-tail dish absent from the pack triggers a question or the
separate unverified estimate option. The grounded path does not silently convert
it to the closest known food.

## Additional product boundaries

### Unverified estimate lane

After `ABSTAIN`, D19/D20 permit a separate Gemini request for one to twenty
unresolved items. It returns broad calorie/macro ranges and assumptions labelled
`llm_unverified_estimate`. Generation may be automatic, but acceptance and
saving are not. Provider or quota failure returns no hardcoded numbers. These
estimates are excluded from the grounded metrics above and need their own
labelled evaluation before any accuracy claim.

### Privacy and face masking

The active edge strips supported metadata, redacts supported text PII and keeps
meal photos ephemeral. Pixel-level face-blur utilities are tested but are not
connected to compressed-image ingestion; visible faces may still reach the
provider. No EatBetter privacy behavior is inferred from screenshots.

### Correction telemetry and training

Review corrections can be written to a privacy-minimized, process-local JSONL
store and prepared by an operator curation script. They do not automatically
become labels, catalogue rows or model updates. No model is trained in this
repository. Human verification, licence review and offline regression gates are
required before a correction could become release evidence.

## Evidence boundary

Repository measurements are reproducible with `make eval`,
`python eval/retrieval_eval.py` and the committed tests. The August full-set
replay was **10/80 commit**, **70/80 ask**, item F1 **0.15**, FP rate **86.0%**,
and **12.7% MAPE over 2/2 eligible and covered rows**; retrieval was Recall@1/5
**100.0%**, MRR **1.000**, with **0/22** false accepts on absent rows. The
current published snapshot is **7/77 commit**, **70/77 ask**, **9% coverage**,
item F1 **0.38**, FP rate **40.5%**, with **38 variants**, 30/30 positive
Recall@1, and 0/8 false accepts; README's
[evidence snapshot](../../README.md#evidence-snapshot) and `make claims` own
those numbers.

No competitor screenshot pair or user photo is committed. Local presentation
media is not clean-clone, CI or benchmark evidence, so this document contains no
links into ignored local folders. Historical iOS smoke in
[PR #191](https://github.com/zexy2/mealog/pull/191) is runtime evidence
for selected flows only; it is not current-release device proof, offline
accuracy, visual-counting accuracy or deployment proof.

This comparison demonstrates bounded Mealog properties and honestly names the
coverage cost. It does not establish that Mealog beats EatBetter overall.
