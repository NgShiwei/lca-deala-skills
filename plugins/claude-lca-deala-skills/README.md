# Claude LCA and DEALA agent skills

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
- **ecoinvent**: `skills/lca-calculator/scripts/ecoinvent_setup.py` connects to
  ecoinvent's servers (through the `ecoinvent_interface` and `bw2io` packages)
  to download the database you are licensed for, only when you run it. It asks
  for your ecoinvent password in your own terminal and stores it with
  `ecoinvent_interface` in that package's settings folder on your machine.
  Claude is instructed never to ask for the password in chat, and the script
  never prints it.
- **Everything else** reads and writes files in your project only.

## Setting up Python

The two Brightway skills need Python 3.11 with a pinned set of packages. The
repository's
[SETUP.md](https://github.com/NgShiwei/claude-lca-deala-skills/blob/main/SETUP.md)
walks through it, and `skills/lca-calculator/scripts/check_environment.py`
checks the result and prints the fix for anything wrong.

Source, tests and issues:
[github.com/NgShiwei/claude-lca-deala-skills](https://github.com/NgShiwei/claude-lca-deala-skills).
