# Setting up the environment

The skills that run Brightway (`lca-calculator`, `deala-calculator`) need a
Python 3.11 environment with a pinned Brightway 2.5 stack and `deala`. The other
two (`lci-extractor`, `supply-chain-optimizer`) need only pandas and networkx,
and so does the toy example.

Commands are written for macOS/Linux and Windows alike. Where the shells
differ, both forms are given. On Windows, if `python` is not on your `PATH`,
the `py` launcher works for step 1 (`py -3.11 -m venv .venv`); after that,
always use `python` inside the activated environment (see step 1).

## 1. Python 3.11, in a virtual environment

```
python3.11 -m venv .venv                # macOS / Linux
py -3.11 -m venv .venv                  # Windows

source .venv/bin/activate               # macOS / Linux
.venv\Scripts\activate                  # Windows
```

A dedicated environment matters: premise and bw2calc pin numpy below 2.0,
which will fight anything else already installed.

**Once the environment is active, use `python`, never `py -3.11`.** The `py`
launcher honours an explicit version over the active environment, so
`py -3.11 -m pip install` installs into the *system* Python and leaves both the
venv and your Jupyter kernel untouched. That split is the most common way this
setup goes wrong; see Troubleshooting.

## 2. Install the packages: two files, in this order

From the folder that holds `requirements.txt` (keep the double quotes; they
stop a space in the path from breaking the command):

```
cd "<path to claude-lca-deala-skills>"
python -m pip install -r requirements.txt
python -m pip install --no-deps -r requirements-deala.txt
```

**`--no-deps` on the second command is not optional.** `deala` 1.2.1 declares
the old Brightway 2. Without `--no-deps`, pip downgrades the Brightway 2.5
packages you just installed and every skill stops working. Listing `deala` in
the first file instead makes pip give up and install nothing at all. The
comments in both files explain the details; please don't merge them.

`python -m pip check` will then complain that `brightway2 2.4.7` wants older
packages. **That is expected. Do not act on it.**

## 3. Windows only: `PYTHONIOENCODING`

Brightway's logs contain characters the default Windows console encoding
cannot print, and a run dies part-way through without this:

```
set PYTHONIOENCODING=utf-8              # cmd
$env:PYTHONIOENCODING = "utf-8"         # PowerShell
```

macOS and Linux need nothing here.

## 4. Check the environment

Run the shared check **in the interpreter that will do the work**: inside the
activated venv, or from a notebook cell running on the venv's kernel.

```
python plugins/claude-lca-deala-skills/skills/lca-calculator/scripts/check_environment.py
```

It prints `sys.executable` and checks, failing with the fix for each problem:

| check | why |
|---|---|
| Python 3.11 | the version the pins were verified on |
| `bw2data 4.7`, `bw2calc 2.5.0`, `bw2io 0.9.17` | Brightway 2.5. A 3.x `bw2data` means `--no-deps` was missed |
| `matrix_utils >= 0.6.3` | below it, DEALA-Cost scoring crashes on `.A1` |
| `ecoinvent_interface >= 3.1` | 3.0 fails the ecoinvent login with `unauthorized_client` |
| `deala 1.2.1` unmodified, `brightway2 2.4.7`, `plotly` | deala will not import without the last two; a hand-edited deala is state no other machine has |
| `PYTHONIOENCODING` (Windows) | see step 3 |

Add `--no-deala` if you only do environmental work.

## 5. The offline tests

These need no Brightway and no licence, only `pandas`, `networkx` and
`pytest`, so any Python 3.8+ environment will do:

```
python -m pip install pytest            # if it isn't installed yet
python -m pytest
```

They cover the graph contract, the toy supply chain, the environment check's
logic and the private-term guard.

## Troubleshooting

### The kernel and the installer are different interpreters

**Symptom.** `ModuleNotFoundError` for a package you just installed; a package
stuck at the wrong version; either ecoinvent failure in the next section.

**Cause.** The packages went into one Python and the notebook runs another.
Anaconda's base environment is the usual culprit, or `py -3.11` used after
activating a venv.

**Check** by running `check_environment.py` from a notebook cell (prefix the
line with `!`) and reading its first line, `interpreter : ...`. It must point
inside your `.venv`.

**Fix.** Register the venv as a kernel and select it in Jupyter:

```
python -m pip install ipykernel
python -m ipykernel install --user --name lca-deala --display-name "lca-deala (3.11)"
```

### `SyntaxError: invalid non-printable character U+00A0`

A non-breaking space arrived with copied-and-pasted code, usually in the
indentation of a continuation line. It is invisible. The line number in the
error is reliable: clear that line's leading whitespace and retype it.
