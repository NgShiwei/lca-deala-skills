# Toy supply chain: a small problem with a known answer

A made-up product is made in three steps, **Grow**, **Process** and
**Finish**. Each step can happen in country **A**, **B** or **C**, and the
product can be shipped to another country after any step. The question is the
one a real study asks: *which country should do each step, so that the
finished product costs as little as possible?*

The answer, worked out by hand below, is **1.1452 USD per kg of finished
product: grow in B, ship to C, then process and finish in C.**

Every number is invented. The example exists so that the skills have a ground
truth:

- **After installing,** run it. It needs only pandas and networkx (no
  Brightway, no deala, no licence) and must end with
  `OK: matches the hand calculation`. Anything else means the installed code
  doesn't behave as documented.
- **When building a real study,** use it as the reference for what each input
  table looks like and what the code does with it. Every input here has a
  real-study counterpart (see the last section).

```
python run_toy.py
```

## The inputs

**`process_costs.csv`**: what each step costs in each country, in USD per kg
of *that step's own output* (1 kg of grown crop, 1 kg of processed material,
1 kg of finished product).

| column | meaning |
|---|---|
| `process_name` | a readable label only |
| `country` | where the step is done |
| `process_base` | which step; must match a name in `STEPS` in `run_toy.py` |
| `process_cost` | USD per kg of the step's output |

**Country C has no `Grow` row: C cannot grow the crop.** It is, though, the
cheapest place to process and to finish. That is deliberate. It checks that a
country missing data for a step is treated as *unable* to do it, not as doing
it for free.

**`scaling_factors.csv`**: how many kg of each step's output go into 1 kg of
finished product, as one list per country in step order (Grow, Process,
Finish). B's `[2.2, 1.3, 1.0]` means that in B it takes 2.2 kg of grown crop
and 1.3 kg of processed material to make 1 kg of finished product. This is
what turns "USD per kg of crop" into "USD per kg of *finished product*", so
the steps can be added up. The lists are matched to the steps by position, so
C's list still has a first entry. It is never used, because C has no `Grow`
cost.

**`distances.csv`**: the distances the shipping cost is built from, one row
per (from, to) pair of countries. Countries are identified by 3-letter codes,
as real distance data is; here `AAA`, `BBB` and `CCC` stand for A, B and C
(the mapping is `ISO2_TO_ISO3` in `run_toy.py`).

| column | meaning |
|---|---|
| `isoA`, `isoB` | from country, to country |
| `short` | `1` if the two countries are neighbours: the product goes by land all the way |
| `roaddistance` | km by land, used when `short` is 1 |
| `capitalport1` | km by land from the origin to its sea port |
| `seadistance` | km by sea, port to port |
| `capitalport2` | km by land from the destination's port inland |

**`RATES`** in `run_toy.py`: freight cost in USD per tonne per km, for lorry
(road), train (rail) and sea. `GLO` is the global rate, used for any country
without a rate of its own.

## The hand calculation

### 1. Shipping cost per kg

A land leg of up to 800 km goes by road (0.20 USD per tonne-km), a longer one
by rail (0.10); sea costs 0.004. The cost per tonne is divided by 1000 to get
the cost per kg.

| from → to | legs | USD per tonne | USD per kg |
|---|---|---|---|
| A ↔ B | neighbours: 600 km road × 0.20 | 120 | 0.120 |
| A ↔ C | 100 km road × 0.20 + 5000 km sea × 0.004 + 900 km rail × 0.10 | 130 | 0.130 |
| B ↔ C | 300 km road × 0.20 + 4000 km sea × 0.004 + 200 km road × 0.20 | 116 | 0.116 |

Staying in the same country costs nothing to ship.

### 2. The cost of each move, per kg of finished product

Each move is "do a step in one country, then send its output to the country
that does the next step". Its cost is

```
scaling factor × (step cost + shipping cost)       shipping = 0 if it stays put
```

For example, growing in B and shipping the crop to C costs
2.2 × (0.25 + 0.116) = 0.8052 USD per kg of finished product.

### 3. The cheapest route, working backwards

- **Finish.** Finishing costs 0.10 in C against 0.40 in A and 0.45 in B, and
  shipping the finished product anywhere adds at least 0.116. So: finish in C
  and sell it there, for 0.10.
- **Process.** The processed material has to reach C. Processing in C costs
  1.2 × 0.20 = 0.24. Processing in A and shipping to C costs
  1.25 × (0.50 + 0.130) = 0.7875; in B, 1.3 × (0.60 + 0.116) = 0.9308. So:
  process in C.
- **Grow.** Only A and B can grow, and the crop has to reach C. From B:
  2.2 × (0.25 + 0.116) = 0.8052. From A: 2.0 × (0.30 + 0.130) = 0.86. So: grow
  in B.

| grow → process → finish | Grow move | Process move | Finish move | total |
|---|---|---|---|---|
| **B → C → C** | **0.8052** | **0.24** | **0.10** | **1.1452** |
| A → C → C | 0.86 | 0.24 | 0.10 | 1.20 |
| A → A → C | 2.0 × 0.30 = 0.60 | 0.7875 | 0.10 | 1.4875 |
| A → A → A (never leave A) | 0.60 | 1.25 × 0.50 = 0.625 | 0.40 | 1.625 |

The cheapest route costs **1.1452 USD per kg of finished product**.

**The wrong answer this example guards against.** If C's missing `Grow` cost
were treated as 0 instead of "C can't do this", the route would start in C and
never leave: 0 + 0.24 + 0.10 = **0.34**. That is less than a third of the true
cost, for a route that cannot exist. A missing row must mean "can't", never
"free".

## Reading the output

The script prints the route twice. First, the graph's own listing:

```
Total: 1.14520   (6 nodes)
  L1  B           0.00000   Grow
  L2  C           0.80520   Process
  L3  C           0.24000   Finish
  L4  C           0.10000   At market
  L5  END         0.00000   END
```

Each line is one **stage** of the route: the stage number, the country, the
cost of *getting to* that stage, and the stage's name. So the Process line
carries 0.8052, the cost of growing in B and shipping to C, because that is
what it took to arrive at "Process, in C". Then the same route in plain words:

```
Cheapest route:
  Grow     in B; the product is shipped from B to C
  Process  in C; the product stays in C
  Finish   in C; the product stays in C and is sold there
Cost: 1.1452 USD per kg of finished product
```

### The stages of the graph

The optimiser sees the problem as a chain of stages, with one box per country
at each stage:

```
START → Grow (A B C) → Process (A B C) → Finish (A B C) → At market (A B C) → END
```

- Getting from START into Grow is free: the optimiser may start anywhere.
- Each arrow between stages is a move from part 2: do the step, ship the
  output. A move with no cost row (Grow in C) has no arrow at all, which is
  why C can never be the starting country.
- **At market** is where the finished product ends up. It isn't a step of its
  own and costs nothing to leave. It exists so that Finish is charged like
  every other step, on the arrow *out of* it, shipping included.

## From the toy to a real study

| here | in a real study |
|---|---|
| `process_costs.csv`, typed in | each step's cost scored with deala (`deala-calculator` skill, `score_native`), or its footprint with `lca-calculator` |
| `scaling_factors.csv` | the mass balance of the real process chain |
| `distances.csv` | a real country-to-country distance table |
| `RATES`, typed in | deala's freight prices (`transport_rates`, needs Brightway) |
| "C cannot grow" | countries without data for some steps; pass `countries_for_step` to `build_edge_table` |
| `STEPS` + `At market` | the study's own steps, in order, plus the market stage |

The code from the shipping table onwards is the same in both. In the source
repository, `tests/test_toy_chain.py` checks every number on this page.
