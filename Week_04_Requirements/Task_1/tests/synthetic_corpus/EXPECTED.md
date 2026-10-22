# Synthetic corpus: planted cases

Domain: a city bike-sharing app (deliberately unrelated to the example corpus).
Input directory for the test: `tests/synthetic_corpus/docs/` (this file is outside it).

| Doc | Style |
|---|---|
| kickoff_meeting_2025-03-03.txt | meeting notes |
| email_ride_rules.eml | email with quoted reply |
| feature_wishlist.md | feature wishlist |
| support_survey_2025.txt | survey summary |

## Planted cases and expected handling

1. **Semantic duplicate**: real-time map of available bikes, in the meeting notes ("see
   available bikes on a map, updated in real time") and the wishlist ("Live map that
   shows where free bikes are parked right now"). Expected: ONE requirement, sources =
   meeting notes + wishlist.
2. **Second duplicate**: support refunds rides from the admin console (meeting notes +
   survey). Expected: one requirement with both sources.
3. **Conflict**: ride auto-ends after 15 min (meeting notes, 2025-03-03) vs. 5 min
   (email, 2025-04-10, explicit DECISION). Expected: keep 5 min; the 15 min version is in
   the blacklist as `conflict`, pointing to the kept requirement.
4. **Nonsensical**: "predict where I want to go ... with 100% accuracy, and teleport the
   bike to me". Expected: blacklist, `nonsensical`.
5. **Out of scope**: "order new office chairs for the support team", "better parking spot
   near the office", "broken coffee machine". Expected: not extracted (small talk/logistics)
   or blacklisted as `out_of_scope`.
6. **Deferred**: gamification badges postponed to version 2. Expected: priority `Won't`,
   or blacklisted as out of scope citing the decision.
7. **Priority cues**: QR unlock "must" -> Must; GPS deletion "mandatory" -> Must; dark mode
   "if possible" -> Could; reservation "would be nice" -> Could.
8. **Completeness**: about 15-17 distinct needs should be kept, including docking stations
   with free slots, platform versions, GPS-trace retention, 2-second profile loading, ride
   history in the admin console, low-battery dashboard, subscription plan, reservation and
   its expiry notification.
