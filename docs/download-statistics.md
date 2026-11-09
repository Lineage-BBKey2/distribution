# Download statistics

The `Track ROM downloads` GitHub Actions workflow runs daily at 00:17 UTC.
It reads the published releases in `Lineage-BBKey2/distribution`, including
prereleases, and records every uploaded asset's cumulative download counter.
It follows pagination for both releases and assets. GitHub-generated source
archives are not uploaded release assets and are not included.

## Output

- `data/downloads.csv`: append-only observation history (stored by atomic rewrite).
- `stats/downloads-total.svg`: cumulative counters across the full recorded history.
- `stats/downloads-30days.svg`: the same cumulative counters for the latest 30 UTC calendar dates.

The README embeds both SVG files. No Pages site or external chart service is
required. Each chart has separate panels for `lineage-*.zip` OTA files and
`LOS*.zip` installation bundles. Other filenames appear in a third panel if
present. `boot.img` and `recovery.img` are recorded in the CSV but excluded
from both charts. The recent chart includes observations in its date window.

## Operation

The workflow must be committed to `main`. Run it initially from
**Actions > Track ROM downloads > Run workflow**, selecting `main`.
The first successful run creates the CSV and both cumulative chart files.
Subsequent runs update them in one commit to `main`. The workflow never
edits the README itself. When upgrading from the version with a rate chart,
the workflow removes the tracked `stats/downloads-rate.svg` automatically.

The automatic `GITHUB_TOKEN` needs `contents: write`, declared in the YAML.
No personal access token is needed. If pushing fails, inspect the workflow
error and the repository/organization rules: branch protection or an
organization policy may prevent direct commits by GitHub Actions.

Schedules are approximate and may be delayed or skipped. Check the Actions
page for failures. GitHub may disable schedules in public repositories after
60 days with no repository activity; successful daily statistics commits
provide regular repository activity. An automated push with `GITHUB_TOKEN`
does not trigger ordinary push workflows.

For manual local regeneration from saved history:

```bash
python3 -m pip install matplotlib
python3 scripts/track_downloads.py --render-only
```

This does not query GitHub or append an observation. Collection additionally
requires the GitHub CLI (`gh`), authenticated using `gh auth login` locally
or the workflow's `GH_TOKEN`. The scheduled job uses GitHub-hosted Ubuntu,
which supplies `gh`.
