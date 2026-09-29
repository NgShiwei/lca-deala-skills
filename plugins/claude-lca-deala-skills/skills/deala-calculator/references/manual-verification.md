# Verifying a DEALA cost score by hand

The point of this document: a DEALA cost score is produced by a solver over a
sparse matrix, which is not something a reader can check. The hand calculation
below reduces it to arithmetic anyone can follow, and shows the two agree to
six decimal places. Run it on one activity before reporting any cost result, and
re-run `--all` after any change to the injection.

## The claim

For a **cut-off** activity (all upstream technosphere inputs zeroed), the native
DEALA-Cost score equals

```
cost = Σ(input_amount × unit_price) / production_amount        [USD per reference unit]
```

where the sum runs over the exchanges pointing into the DEALA input database,
and each `unit_price` is that input activity's own DEALA-Cost score.

**Why unit prices come out of the solver too.** Each DEALA input activity has
`production: 1` plus a `type='biosphere'` exchange to a `marketsphere` flow whose
amount is its price. Scoring it alone with FU `{act.id: 1}` therefore returns
exactly that price — USD/kWh, USD/MJ, USD/kg, USD/tkm, USD/h. No price table is
hard-coded anywhere; the numbers come out of the database.

**Why the division by production.** The functional unit is one reference unit of
output, matching how the environmental side scores its cut-off activities. If an
activity produces 3070 kg, its per-kg cost is the summed input cost divided by
3070. Pick an activity with production ≠ 1 for the worked example, so that term
is exercised.

## Worked example (illustrative numbers)

The activity and every number below are **invented** to show the shape of the
output. Run the command on the user's own project to get real ones.

Command:

```bash
python scripts/verify_cost.py --project <project> \
   --db "<costed modular db>" \
   --activity "DEALA, Cutoff NP, Toy pressing" --country AA
```

Output shape:

```
[env] matrix_utils 0.6.3, bw2calc 2.5.0, bw2data 4.7, scipy 1.13.1, numpy 1.23.5
Manual verification — DEALA, Cutoff NP, Toy pressing, at processing, {AA}
========================================================================
Step 1. Cost inputs linked into the DEALA input database:
    electricity - Non-household, <band> [AA]
        1.6 kWh x 0.150000 USD/kWh = 0.240000 USD
    consumables and supplies - Tap water production [GLO]
        0.8 kg x 0.002500 USD/kg = 0.002000 USD
    personnel - Manufacturing [AA]
        0.005 h x 12.000000 USD/h = 0.060000 USD

Step 2. Unit prices above are each input activity's own DEALA-Cost score
        (production:1 + a marketsphere price flow), scored alone.

Step 3. Sum of contributions   = 0.302000 USD
        Production amount      = 2
        Manual cost            = 0.302000 / 2 = 0.151000 USD/kg

Step 4. Native bc.MultiLCA score = 0.151000 USD/kg
        ratio native/manual      = 1.000000
        abs diff                 = 4.2e-09

PASS — native scoring reproduces the hand calculation.
```

### Reading the three terms

| Input | Amount | Unit price | Contribution | Where the amount comes from |
|---|---|---|---|---|
| Electricity, country AA | 1.6 kWh | 0.150000 USD/kWh | 0.240000 USD | the process's own electricity exchange, copied 1:1 |
| Tap water production, GLO | 0.8 kg | 0.002500 USD/kg | 0.002000 USD | the process's tap-water exchange |
| Personnel — Manufacturing, country AA | 0.005 h | 12.000000 USD/h | 0.060000 USD | a labour rate in h/tonne × production kg ÷ 1000 |

Total **0.151 USD/kg**, of which electricity is 79 %, labour 20 %, water 0.7 %.
Check that shape is plausible for the step: that is the second thing to check
after the arithmetic. The labour term is the one worth re-reading: it is the only
input not taken from the physical inventory but from a per-tonne rate, so an
error there would not show up as a broken link, only as a wrong number.

A residual `abs diff` around 1e-09 is float64 accumulation order, not a
modelling difference.

## Regression gate over every activity

```bash
python scripts/verify_cost.py --project <project> \
   --db "<costed modular db>" --all --csv crosscheck.csv
```

Output shape:

```
[read] <n> cut-off activities in '<costed modular db>'
[cross-check] <n> activities; max abs diff = <~1e-08>; ratio range 1.000000 .. 1.000000
[worst] <activity name>: manual <x> vs native <x> (ratio 1.000000)
PASS — every activity's native score reproduces its hand calculation.
```

This is cheap because `cross_check_all` prices the *distinct* input activities
once and then sums per activity, rather than re-scoring the inputs for every
activity.

**Sanity band:** every activity positive, and the range plausible for the
inventory. A zero or a negative is a broken link, not a cheap process.

## When manual and native legitimately differ

Native DEALA cost is `LCA(process) − Σ LCA(technosphere_input) × amount` — it
*subtracts* the cost already embodied in upstream technosphere inputs, to avoid
double-counting along a chain. For cut-off activities every upstream input is
zeroed, so the subtraction term is zero and the two forms coincide exactly.

On a **non-cut-off** process the naive sum would double-count and the two will
disagree. That is not a bug in the native score — it is the native score being
right. If `verify` ever reports FAIL, check whether the activity still has live
upstream inputs before suspecting the method.
