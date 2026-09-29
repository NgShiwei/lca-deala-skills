# LCA and DEALA agent skills

Four skills that help Claude carry out life-cycle work with
[Brightway 2.5](https://docs.brightway.dev):

- **lca-calculator**: environmental life-cycle assessment. Choose an impact
  method, run the calculation, edit safe working copies of databases, build a
  new process from your own data, and recover from duplicate or broken
  activities.
- **deala-calculator**: life-cycle cost with the
  [deala](https://pypi.org/project/deala/) package. Price a process's inputs,
  score its cost, check that score by hand, and build a cost table that
  includes shipping between countries.
- **lci-extractor**: read a scientific article (PDF plus supplementary
  information) and transcribe its life-cycle inventory, normalised to the
  functional unit, with the source of every number recorded.
- **supply-chain-optimizer**: find which country should do each step of a
  supply chain so that the whole chain has the lowest footprint or cost.

The skills ask before they assume. Every methodological choice (impact
method, allocation, proxies, electricity band, cost year) is put to you, and
when a search finds zero or several candidates the skill stops and asks rather
than guessing.

## Try it first

`examples/toy-chain/` is a small invented supply chain with a known answer. It
needs only pandas and networkx: `python examples/toy-chain/run_toy.py` should
end with `OK: matches the hand calculation`.

## What the plugin runs, and what it sends

The plugin has no hooks, no MCP servers and no background processes. It only
contains instructions and Python scripts that Claude runs on your machine when
a task needs them:

- **Calculations** run locally, in your own Python environment, on your own
  Brightway databases. Nothing is uploaded.
- **ecoinvent credentials** are the only credential the plugin touches, in
  one script, `skills/lca-calculator/scripts/ecoinvent_setup.py`, which you
  run yourself in your own terminal:
  - **What it reads:** your ecoinvent username and password, from the
    environment variables `ECOINVENT_USERNAME` / `ECOINVENT_PASSWORD` or
    `EI_USERNAME` / `EI_PASSWORD` if you set them, otherwise from the
    `ecoinvent_interface` settings folder on your machine. If none is stored,
    it asks you in your terminal (the password with `getpass`, not shown) and
    stores them in that same folder with `ecoinvent_interface`.
  - **Where they go:** only to ecoinvent's own login server, through the
    `ecoinvent_interface` and `bw2io` packages, to download the ecoinvent
    release your licence covers. They are sent nowhere else, and never to
    Anthropic or to the plugin's author.
  - **What is shown:** the username only. The password is never printed or
    logged, and Claude is instructed never to ask for it in chat. `--check`
    reports what is stored without contacting ecoinvent.
- **Everything else** reads and writes files in your project only.

## Setting up Python

The two Brightway skills need Python 3.11 with a pinned set of packages. The
repository's
[SETUP.md](https://github.com/NgShiwei/lca-deala-skills/blob/main/SETUP.md)
walks through it, and `skills/lca-calculator/scripts/check_environment.py`
checks the result and prints the fix for anything wrong.

Licensed under BSD 3-Clause (see `LICENSE`). ecoinvent and any other
database you use with these skills remain under their own licences.

Source, tests and issues:
[github.com/NgShiwei/lca-deala-skills](https://github.com/NgShiwei/lca-deala-skills).
