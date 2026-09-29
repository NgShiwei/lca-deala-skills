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

## 5. ecoinvent: credentials and the database

ecoinvent is licensed, so it is neither in this repository nor on pip. One
script stores your credentials and installs the database. **Run it yourself, in
your own terminal**: it asks for your password with `getpass`, which needs a
real terminal, and your password should never pass through a chat with an
agent.

```
python plugins/claude-lca-deala-skills/skills/lca-calculator/scripts/ecoinvent_setup.py --project <project>
```

1. **Credentials.** If none are stored, it asks for your ecoinvent username
   (the username, not your email address) and password, and stores them with
   `ecoinvent_interface.permanent_setting()` in
   `~/.config/pylca/EcoinventInterface/secrets` (macOS/Linux) or
   `%LOCALAPPDATA%\pylca\EcoinventInterface\secrets` (Windows): outside any
   repository, so they cannot be committed by accident. If some are stored, it
   shows the username and asks whether to use them. `--reprompt` replaces them.
   `ECOINVENT_USERNAME` / `ECOINVENT_PASSWORD`, or `EI_USERNAME` / `EI_PASSWORD`,
   in the environment take precedence over the stored ones.
2. **Project.** `--project` has no default. A project that doesn't exist is
   created, and the script says so: if you didn't expect that, check the name.
3. **Import.** If ecoinvent or its biosphere is missing, it offers to download
   and import both: **about 35 minutes and 1.6 GB, default No.** The release
   archives are cached, so a repeat import doesn't re-download.
4. **Verification.** It then asserts that both databases and the IPCC 2021
   GWP100 method exist.

`--version` (default `3.10`) and `--system-model` (default `cutoff`) choose
another release. `--check` is read-only: it prints the stored username (never
the password) and what the project holds; this is what an agent runs to see
where you are.

Other licensed databases (Agri-footprint, for example) are bring-your-own: this
release has no importer for them.

## 6. The offline tests

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

**Check** from inside the notebook, with `%run` so it runs in the kernel's own
interpreter (`!python ...` would run whatever `python` the shell finds first):

```
%run plugins/claude-lca-deala-skills/skills/lca-calculator/scripts/check_environment.py
```

Its first line, `interpreter : ...`, must point inside your `.venv`.

**Fix.** Register the venv as a kernel and select it in Jupyter:

```
python -m pip install ipykernel
python -m ipykernel install --user --name lca-deala --display-name "lca-deala (3.11)"
```

### Credentials read as `(none)` right after storing them

**Cause.** Something in a long-running Python session (a notebook kernel, say)
resolved the credentials when it was first imported, before you stored them.
Python caches imported modules, so re-running a cell doesn't re-read them.
`ecoinvent_setup.py` itself resolves them fresh on every run.

**Fix.** Restart the kernel, or `importlib.reload(<module>)`, then check with
`ecoinvent_setup.py --project <project> --check`.

### `unauthorized_client` / "Client not allowed for direct access grants"

```
UserWarning: Given credentials can't log in: error 400
HTTPError: 400 Client Error: Bad Request for url:
https://sso.ecoinvent.org/realms/ecoinvent/protocol/openid-connect/token
```

**Not the password**: the credentials are never evaluated.
`ecoinvent_interface` 3.0 and below use a login client that ecoinvent has since
disabled. 3.1 fixed it. `bw2io` doesn't declare the package, so an old copy
already on the machine satisfies it and is never upgraded.

**Fix.** `python -m pip install --upgrade "ecoinvent_interface>=3.1"` in the
interpreter that runs the import (`check_environment.py` flags this).

If it still fails after the upgrade with `invalid_grant`, the username or
password really is wrong: use your ecoinvent *username*, not your email, and
check you can log in at ecoinvent.org without a single-sign-on redirect. A
federated login has no password this route can use.

### `LCIA method not installed: ('ecoinvent-3.10', ...)`

**Symptom.** The databases exist but the method assert fails.

**Cause.** The import ran under a `bw2io` older than 0.9.17, which installs the
methods without their `ecoinvent-3.10` namespace. It doesn't self-heal: once
both databases exist the script skips the import, and the assert fails on every
re-run.

**Fix, and the trade-off.** After fixing the environment, re-install the
methods alone, in minutes:

```
python plugins/claude-lca-deala-skills/skills/lca-calculator/scripts/ecoinvent_setup.py --project <project> --methods-only
```

But the two databases underneath were still written by the wrong `bw2io`, and
import behaviour differs beyond method naming. If results must be reproducible,
delete the project and import again instead.

**Don't use `bd.projects.delete_project(name, delete_dir=True)` for that.** It
removes the project from the registry *before* it checks the directory, and the
directory name carries a hash whose length changed between bw2data versions.
With a project created by an older bw2data, the check then fails on a project
already de-registered: the data is orphaned on disk and the project is gone
from `bd.projects`. Delete the directory by hand instead. Restart the kernel
first, so bw2data releases its SQLite files, then, with `PROJECT` set to the
project name:

```python
import bw2data as bd, pathlib, shutil
PROJECT = "<project>"
base = pathlib.Path(bd.projects._base_data_dir)
assert PROJECT not in {p.name for p in bd.projects}, "still registered: delete_project(PROJECT) without delete_dir first"
cands = [d for d in base.iterdir() if d.is_dir() and d.name.startswith(PROJECT + ".")]
print("deleting:", [d.name for d in cands])
for d in cands:
    shutil.rmtree(d)
```

**Verify either fix** before any real work. A namespace mismatch is otherwise
silent, and every score comes back zero:

```python
import bw2data as bd, bw2calc as bc
bd.projects.set_current("<project>")
act = bd.Database("ecoinvent-3.10-cutoff").random()
lca = bc.LCA({act: 1}, ("ecoinvent-3.10", "IPCC 2021", "climate change",
                        "global warming potential (GWP100)"))
lca.lci(); lca.lcia()
print(act["name"][:60], "->", lca.score)
```

A score of exactly `0.0` means the characterization factors are not linked to
your biosphere. If you see `Brightway2Project: Please use
projects.migrate_project_25`, you are pointed at the wrong project (often
`default`, after a delete). Don't run that migration.

### Windows: `.lci()` kills Python with `0xc06d007f`

**Symptom.** A hard crash with "Windows fatal exception: code 0xc06d007f" the
moment a calculation solves. No Python traceback. Imports, iterating a
database, creating activities and `process()` all work first, so it reads like
a data problem. It is not.

**Cause.** `bw2calc`'s solve delay-loads a DLL from the environment's own
library folder, and that folder is only on `PATH` when the environment is
activated. Running the environment's `python.exe` directly (a conda
environment is the usual case) skips that.

**Fix.** Activate the environment (`.venv\Scripts\activate`, or
`conda activate <env>`) before starting Python or Jupyter, instead of calling
its `python.exe` by full path. For a conda environment that cannot be
activated, prepend its `Library\bin`, `Library\mingw-w64\bin`,
`Library\usr\bin` and `Scripts` folders to `PATH`.

### `SyntaxError: invalid non-printable character U+00A0`

A non-breaking space arrived with copied-and-pasted code, usually in the
indentation of a continuation line. It is invisible. The line number in the
error is reliable: clear that line's leading whitespace and retype it.
