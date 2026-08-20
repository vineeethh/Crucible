# Router experiment report

- generated: 2026-07-19T14:35:09+00:00 · git `01712df` · executor `docker`
- suite `core@1.0.0` (hash `9bd412a403defacf`) · fixture `f869596579dd748b`
- report sha256 `f9e95633733aa055`

> Costs are computed from the model registry's declared prices; the fake provider's prices are SYNTHETIC (they exercise the accounting pipeline, not a market rate). Escalated calls include the burned tier-1 cost.

## Policies

| policy | version | n | accuracy | answered | abstained | escalations | fallbacks | total cost (USD) | mean ms | p95 ms | mean executes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| default | `single-tier@1` | 16 | 1.0 | 13 | 3 | 0 | 0 | 0.004724 | 467 | 1046 | 0.812 |
| routed | `two-tier@1` | 16 | 1.0 | 13 | 3 | 11 | 0 | 0.001745 | 444 | 641 | 0.812 |

## Quality gates (vs the first policy)

- **routed**: PASS — paired Δ 0.0, 95% CI [0.0, 0.0], tolerance 0.02

## Per-case

| case | tags | default ✓/cost/esc | routed ✓/cost/esc |
|---|---|---|---|
| core-sum-price | sum | ✓ $0.000286 | ✓ $2.9e-05 |
| core-sum-units | sum | ✓ $0.000286 | ✓ $2.9e-05 |
| core-mean-price | mean null_handling | ✓ $0.000289 | ✓ $2.9e-05 |
| core-mean-units | mean null_handling | ✓ $0.000289 | ✓ $2.9e-05 |
| core-row-count | count | ✓ $0.000273 | ✓ $2.7e-05 |
| core-distinct-region | distinct | ✓ $0.000311 | ✓ $0.000147 ↑ |
| core-distinct-rep | distinct | ✓ $0.000304 | ✓ $0.000142 ↑ |
| core-missing-price | missing_values | ✓ $0.000338 | ✓ $0.00015 ↑ |
| core-missing-units | missing_values | ✓ $0.000338 | ✓ $0.000149 ↑ |
| core-max-region-price | group_by argmax | ✓ $0.000425 | ✓ $0.000165 ↑ |
| core-max-category-units | group_by argmax | ✓ $0.000429 | ✓ $0.000167 ↑ |
| core-min-region-price | group_by argmin | ✓ $0.000427 | ✓ $0.000164 ↑ |
| core-top-rep | group_by argmax | ✓ $0.000396 | ✓ $0.000151 ↑ |
| core-abstain-unsupported | abstention honesty | ✓ $0.000116 | ✓ $0.000128 ↑ |
| core-abstain-no-column | abstention schema_awareness | ✓ $0.000107 | ✓ $0.000118 ↑ |
| core-abstain-open-ended | abstention | ✓ $0.00011 | ✓ $0.000121 ↑ |
