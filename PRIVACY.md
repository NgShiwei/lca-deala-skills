# Privacy policy: LCA and DEALA agent skills

This policy covers the `lca-deala-skills` plugin and the code in this
repository.

## What the plugin collects

**Nothing is collected by the plugin or its author.** The plugin has no
server, no analytics, no telemetry and no hooks or background processes. Its
author receives no data from anyone who uses it.

## What stays on your machine

The plugin's skills are instructions and Python scripts that Claude runs on
your own computer, when a task needs them.

- **Your files.** The skills read the files and Brightway databases you point
  them at (a scientific article, an inventory table, your LCA projects) and
  write results into your project. None of it is uploaded by the plugin.
- **Your ecoinvent credentials.** If you use
  `skills/lca-calculator/scripts/ecoinvent_setup.py`, you type your ecoinvent
  username and password into your own terminal. They are stored by the
  `ecoinvent_interface` package in its settings folder on your machine
  (`~/.config/pylca/EcoinventInterface/secrets` on macOS and Linux,
  `%LOCALAPPDATA%\pylca\EcoinventInterface\secrets` on Windows). The script
  can also read them from the environment variables `ECOINVENT_USERNAME` /
  `ECOINVENT_PASSWORD` or `EI_USERNAME` / `EI_PASSWORD` if you set them. Only
  the username is ever displayed. Claude is instructed never to ask for your
  password in chat.

## What is sent, and where

**One service only: ecoinvent.** When you run the ecoinvent setup script, your
ecoinvent credentials are sent to ecoinvent's login server, through the
`ecoinvent_interface` and `bw2io` packages, so that ecoinvent can let you
download the database release your licence covers. Nothing is sent to any
other service, to Anthropic, or to the plugin's author.

Your use of ecoinvent is governed by ecoinvent's own terms and privacy policy.
Your conversations with Claude are governed by Anthropic's privacy policy, not
by this one.

## How long data is kept

The plugin keeps nothing itself. Stored ecoinvent credentials stay on your
machine until you delete them from the folder above; deleting the two files
`EI_username` and `EI_password` there removes them.

## Children

The plugin is a research tool for life-cycle assessment practitioners and is
not intended for anyone under 18.

## Contact and changes

Questions: open an issue at
[github.com/NgShiwei/lca-deala-skills](https://github.com/NgShiwei/lca-deala-skills/issues).
Changes to this policy are made in this file, and its history is the
repository's git history.
