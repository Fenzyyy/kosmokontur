# Defense readiness — 20 criteria

## Already implemented in the calculation/web contour

| Criterion | Status | Evidence |
|---|---|---|
| 1 Material balance | ✅ | fuel_model engine + reference cases |
| 2 Capacity / lead time | ✅ | engine checks + canonical investment schedules |
| 3 Economics | ✅ | CAPEX/OPEX/procurement/reservation/TOP/storage/PV |
| 4 Standard constraints | ✅ | checks.py + yearly violations |
| 5 Reproducibility | ⚠️ verify final run | tests + reference vectors |
| 6 Calculation architecture | ✅ | engine/model/checks/scenarios/optimizer |
| 7 Methods / sources | ⚠️ | add source register with method → implementation → limitation |
| 8 Alternatives | ✅ | optimizer + investment frontier |
| 9 Investments / contracts | ✅ | investments.py + source roles |
| 10 Mandatory stress | ✅ | BASE + MANDATORY_STRESS |
| 11 Sensitivity | ⚠️ | analysis.sweep exists; final charts/results still needed |
| 12 Test protocols | ⚠️ | automated tests exist; defense protocol document needed |
| 13 Plan under stress | ✅/⚠️ | stress result is calculated; quantitative narrative needed |
| 14 Risk register | ❌ | must prepare team-specific register |
| 15 Quantified risk impact | ❌/⚠️ | run risk scenarios and record tons/cost/service/time |
| 16 Mitigation / residual risk | ❌ | add measures, cost, effect, residual exposure |
| 17 Stakeholders | ❌ | operator/critical/commercial/suppliers/financing map |
| 18 Risk adaptation | ❌ | show how decisions and obligations change |
| 19 Operator functions / access | ✅/⚠️ | working UI; perform full live demo |
| 20 Save / export / development | ✅/⚠️ | Save/Open JSON + CSV added; final saved BASE/STRESS artifacts still needed |

## Immediate defense package

1. Management note 8–12 pages.
2. One-page BASE vs STRESS summary.
3. Presentation ≤12 slides.
4. Risk register with quantified consequences and residual risk.
5. Stakeholder map.
6. Sensitivity plots and threshold table.
7. Test protocol with expected vs actual results.
8. Saved BASE and STRESS plans/results.
9. CSV/XLSX exports.
10. Supply-chain diagram.
11. Contract-financial architecture.
12. 2035–2040 investment roadmap.

## Final technical smoke test

Install → run → BASE → STRESS → sensitivity → Save → Open → Export CSV → Docker → tests.

The repository must contain only reproducible materials; no tokens/API keys.
