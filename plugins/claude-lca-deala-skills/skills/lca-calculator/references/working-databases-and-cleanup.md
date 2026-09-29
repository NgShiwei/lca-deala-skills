# Working databases & recovery when a run misbehaves

The two habits in this file are what separate a reproducible LCA project from one
that slowly corrupts itself. Read this before any bulk edit or re-run.

## Why work on a copy

Imported reference databases (ecoinvent, Agri-footprint) are expensive to
rebuild and are shared across every calculation. An in-place edit — a zeroed
amount, a stray `.delete()`, a half-finished loop — can silently change results
everywhere and is not undoable without re-importing.

So the standard shape of an LCA editing project is a chain of copies:

```
ecoinvent / Agri-footprint      (reference — never edited)
        └── <db>_working        (working copy — custom processes)
                └── Modular_<db>    (cut-off / modular variant)
                        └── Costed_<db>  (economic layer)
```

Each layer is a `bd.Database(source).copy(target)` (or `working_copy()` in
`lca_helpers.py`). Editing only happens on the deepest working copy.

**Never put "DEALA" in a working database's name.** deala's
`import_DEALA_activities` deletes every database whose name contains "DEALA"
(`deala_io.py:367-370`), so `DEALA <db>` disappears the next time the DEALA
price databases are rebuilt. `working_copy()` refuses such a name.

Before deleting or overwriting a working database, **state the exact name and
confirm** — `del bd.databases[name]` is irreversible.

## Idempotent builds

`activity.copy()` mints a new object with a new code every call. A build loop
that copies without first removing prior copies therefore doubles its output on
every re-run. Two guards fix the whole class of "the numbers grew" bugs:

**Delete-then-copy on a stable name** (`fresh_copy` in `lca_helpers.py`):

```python
for old in [a for a in db if a["name"] == new_name]:
    old.delete()
na = source.copy(); na["name"] = new_name; na.save()
```

**Snapshot exchanges before adding** — iterating the live queryset while adding
re-matches your additions. A DEALA train-cost exchange named
`…freight train, non-hazardous…` contains the substring `transport, freight
train`, so a naive loop adds it again and again:

```python
for e in list(act.exchanges()):     # snapshot; not `act.exchanges()`
    if "transport, freight train" in e["name"].lower():
        act.new_exchange(...).save()
```

## Deleting duplicates when a run goes wrong

Symptoms and fixes:

### Accumulated duplicate copies
A loop ran several times without `fresh_copy`. You now have many same-named
generated activities. Reset with a prefix delete, then re-run the (now
idempotent) build:

```python
from lca_helpers import delete_by_name_prefix
delete_by_name_prefix(db, "DEALA, ", dry_run=True)   # review
delete_by_name_prefix(db, "DEALA, ", dry_run=False)  # then delete
```

### A broken duplicate source (missing production exchange)
Two activities share a name; one lacks a `production` exchange. Brightway then
treats its output as 1 unit, so any process built from it scores orders of
magnitude off (hundreds of times the median of its peers). Diagnose by comparing scores across
peers, then confirm the culprit:

```python
twins = [a for a in db if a["name"] == "<crop>, at farm {CA} Economic, U"]
for a in twins:
    print(a.id, "production:", any(e.get("type")=="production" for e in a.exchanges()),
          "| exchanges:", len(list(a.exchanges())))
```

Fix: rebuild the dependent activity from the *complete* twin, patch any saved
result CSVs, delete the broken twin **only if it has no consumers**:

```python
def consumers(db, act):
    return sum(1 for x in db for e in x.technosphere() if e.input.id == act.id)
```

`delete_broken_duplicates(db, dry_run=True)` automates the safe case (deletes a
production-less activity only when a complete same-named twin remains).

### Prevent recurrence
Harden selectors so they cannot pick a generated copy or a broken twin:

```python
act = [a for a in db
       if selector in a["name"] and "{"+country+"}" in a["name"]
       and not a["name"].startswith(("Cutoff", "DEALA"))
       and has_production(a)][0]
```

Matching on the delimited `"{"+country+"}"` rather than a bare country code also
avoids substring collisions (e.g. `AT` inside `"at farm"`).

## NonsquareTechnosphere: two causes that look identical

`bw2calc.errors.NonsquareTechnosphere: Technosphere matrix is not square: N
activities (columns) and M products (rows)` means the row (product) and column
(activity) index sets differ. Don't guess which way — run the diagnostic and let
it tell you:

```python
from lca_helpers import diagnose_nonsquare
diagnose_nonsquare({my_activity: 1})   # -> orphan_products / orphan_activities
```

It ports the notebook recipe: build the LCA, catch the error, and compare
`lca.product_dict` (rows) against `lca.activity_dict` (columns).

**Cause A — stale datapackage on a just-edited database (rows > cols).** You
created/edited activities with `new_activity` / `new_exchange` and ran the calc
immediately. The links are fine and dependencies are registered, but the edited
database's *datapackage* was never rebuilt, so only that database's activities
became columns while its exchanges still reference input products that have no
producing column. Symptom: a small `N activities` (often 1) against a larger `M
products`, and `orphan_products` are the referenced inputs. **Fix: `db.process()`
on the edited database, then retry.** This is easy to miss because nothing is
actually wrong with the data — it just wasn't committed for calculation. It also
means the lightweight single-activity scratch database is a fine pattern *as long
as you `process()` it* before calculating; you do not need to copy a whole
database for a small what-if edit.

**Cause B — genuine orphan / duplicate activity.** A real database contains an
activity with zero (or mismatched) production exchanges, or a redundant duplicate
producing the same product. Here `orphan_activities` (columns with no product
row) or duplicated producers are the culprit. **Fix:** back up the database
(`db.copy(name + "_backup")`), inspect each orphan (its production exchanges and
who references it as input), and delete the redundant ones — e.g. duplicated
`market for electricity, low voltage` copies already mapped to ecoinvent.

Same error message, opposite fixes — which is why the `activity_dict` vs
`product_dict` comparison is worth running before touching anything.

## After fixing inventory, refresh downstream artefacts

A corrected activity changes any saved results. Re-run the LCA for the affected
activity, patch the results CSV, and regenerate anything derived from it (scaled
contributions, network edge weights) so the fix propagates. Don't leave a stale
CSV next to a corrected database.
