# LCA and DEALA agent skills

Four [Claude Code](https://code.claude.com) skills for life-cycle work with
[Brightway 2.5](https://docs.brightway.dev), packaged as one plugin:

| skill | what it does | needs Brightway |
|---|---|---|
| `lca-calculator` | LCA/LCIA with Brightway 2.5: choose an impact method, run `MultiLCA`, work on safe copies of databases, build a new process from user data, recover from duplicate or broken activities. Also sets up ecoinvent. | yes |
| `deala-calculator` | Life-cycle **cost** with [DEALA](https://pypi.org/project/deala/): price inputs, inject cost exchanges, score them natively, verify the score by hand, and build a transport-aware cost table for the optimiser. | yes |
| `lci-extractor` | Transcribe a life-cycle inventory from a scientific article (PDF + SI), normalised to the functional unit with provenance for every number, and hand it to `lca-calculator`. | no |
| `supply-chain-optimizer` | Turn per-step, per-country scores into a layered graph and find the lowest-impact (or lowest-cost) route across countries and process steps. | no |

The skills ask before they assume: every methodological choice (impact
method, allocation, proxy, electricity band, cost year) goes to you, and a
selector that finds zero or several candidates stops rather than guessing.

## Install

In Claude Code:

```
claude plugin marketplace add NgShiwei/lca-deala-skills
claude plugin install lca-deala-skills@ngshiwei
```

The skills then appear as `lca-deala-skills:lca-calculator`,
`lca-deala-skills:deala-calculator` and so on. Claude uses them on its
own when a task matches; you can also call one by name.

The two Brightway skills need a Python environment with the pinned Brightway
2.5 stack and `deala`. Clone this repository and follow **[SETUP.md](SETUP.md)**:
a Python 3.11 venv, two `pip install` commands (the second with `--no-deps`),
and one environment check that tells you the fix for anything wrong.

## Licensed data

ecoinvent is licensed to you, not to the agent. The skills follow these rules,
and so should you:

- **Your ecoinvent password is never typed into a chat.** You store it once, in
  your own terminal, with
  `plugins/lca-deala-skills/skills/lca-calculator/scripts/ecoinvent_setup.py`.
  It keeps the credentials outside any repository. The agent can check what is
  stored (it sees the username, never the password) but cannot enter them.
- **The ecoinvent import takes about 35 minutes and 1.6 GB.** An agent may start
  it only after telling you that and getting your yes.
- **Licensed exports are never read whole**, and licensed data, or anything
  derived from it row for row, is never committed or shared.

ecoinvent is the only database with a setup script in this release. Any other
licensed database (Agri-footprint, for example) is bring-your-own.

## Try it without Brightway

`plugins/lca-deala-skills/examples/toy-chain/` is a made-up supply chain
(three countries, three steps, invented numbers) that runs the real transport,
edge-table and graph code with only pandas and networkx. Its README works the
answer out by hand.

```
python plugins/lca-deala-skills/examples/toy-chain/run_toy.py
```

## Tests

```
python -m pip install pandas networkx pytest country_converter
python -m pytest
```

Everything runs offline, with no Brightway and no licence: the graph contract,
the toy chain, the DEALA edge-table gates and price-file handling, the
environment check's logic, the ecoinvent credential handling, and the
lci-extractor self-tests. `tools/check_private_terms.py` is the maintainer's
pre-release guard against leaking a private study's data into this repository;
its term list is kept off the repository, so that one check is skipped in a
fresh clone.

## Releasing an update

Installed copies update only when the plugin's version changes. For every
release:

1. Bump `version` in `plugins/lca-deala-skills/.claude-plugin/plugin.json`
   (`0.1.0` → `0.1.1` for fixes, `0.2.0` for new behaviour). Set it only there,
   never in `marketplace.json` too.
2. Run `python -m pytest` and `python tools/check_private_terms.py`; both must
   pass.
3. Commit and push. Users get it with
   `claude plugin update lca-deala-skills@ngshiwei`, or automatically if
   they turned on auto-update for the `ngshiwei` marketplace in `/plugin`.

A push without a version bump reaches nobody who has already installed.

## Privacy

The plugin collects nothing and has no server. It sends data to one service
only, ecoinvent, and only when you run the ecoinvent setup script. Details:
[PRIVACY.md](PRIVACY.md).

## Licence

BSD 3-Clause (see [LICENSE](LICENSE)), the same licence as Brightway and deala.
The licence covers this repository's code and text only. ecoinvent and any
other database you use with the skills stay under their own licences.

## Layout

```
.claude-plugin/marketplace.json          the marketplace (this repository)
plugins/lca-deala-skills/
  .claude-plugin/plugin.json             the plugin
  skills/<skill>/SKILL.md                the four skills, with scripts/ and references/
  examples/toy-chain/                    the offline worked example
requirements.txt, requirements-deala.txt the pinned environment (see SETUP.md)
LICENSE                                  BSD 3-Clause (a copy ships inside the plugin)
tests/, tools/                           offline tests and the pre-release guard
```
