# Toy supply chain: three countries, three steps

Every number here is invented. The example exists to show the whole
cost-to-route pipeline on data small enough to check by hand, and it doubles as
the offline test (`tests/test_toy_chain.py` at the repository root). It needs
pandas and networkx only: no Brightway, no licence.

```bash
python run_toy.py
```

## The inputs

| file | what it is | where a real study gets it |
|---|---|---|
| `process_costs.csv` | cost of each step in each country, USD per kg of that step's output | `deala_helpers.score_native` on the cut-off activities |
| `scaling_factors.csv` | kg of each step's output per kg of final product, one bracketed list per country | the mass ratios of the modular chain |
| `distances.csv` | the distance table the transport model reads: road only for neighbours (`short == 1`), otherwise land + sea + land | the project's distance data |
| `RATES` in `run_toy.py` | freight rates, USD per tonne-km | `deala_helpers.transport_rates` |

Country **C cannot grow**: it has no `Toy grow` cost row. It is the cheapest at
both later steps, which is exactly the country an incorrect graph builder lets
win, by charging its missing first step 0.0.

## The hand calculation

**Transport** (USD/kg = USD/t ÷ 1000; road ≤ 800 km, rail beyond):

| pair | legs | USD/t | USD/kg |
|---|---|---|---|
| A↔B | 600 km road × 0.20 | 120 | 0.120 |
| A→C | 100 road × 0.20 + 5000 sea × 0.004 + 900 rail × 0.10 | 130 | 0.130 |
| B→C | 300 road × 0.20 + 4000 sea × 0.004 + 200 road × 0.20 | 116 | 0.116 |

**Edge weight** = scale × cost within a country, scale × (cost + transport)
across countries. The three cheapest ways into C's later steps:

| route (grow → process → finish) | grow edge | process edge | finish edge | total |
|---|---|---|---|---|
| **B → C → C** | 2.2 × (0.25 + 0.116) = 0.8052 | 1.2 × 0.20 = 0.24 | 1.0 × 0.10 = 0.10 | **1.1452** |
| A → C → C | 2.0 × (0.30 + 0.130) = 0.86 | 0.24 | 0.10 | 1.20 |
| A → A → C | 2.0 × 0.30 = 0.60 | 1.25 × (0.50 + 0.130) = 0.7875 | 0.10 | 1.4875 |

The optimum is **1.1452 USD/kg, grown in B, processed and finished in C**.

A builder that charged C's missing grow step 0.0 would report
0 + 0.24 + 0.10 = **0.34** via C → C → C instead: less than a third of the true
cost, and a route that cannot exist.

## Reading the printed pathway

`format_pathway` labels each edge with the node it arrives at, so each line's
weight is the cost of the **previous** step shipped to that country:

```
Total: 1.14520   (6 nodes)
  L1  B           0.00000   Toy grow                START -> B: free choice of origin
  L2  C           0.80520   Toy process             grow in B, shipped to C
  L3  C           0.24000   Toy finish              process in C
  L4  C           0.10000   Toy finish, at market   finish in C
  L5  END         0.00000   END                     pass-through layer, free
```
