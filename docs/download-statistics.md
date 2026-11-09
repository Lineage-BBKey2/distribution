# Download statistics

The `Track ROM downloads` GitHub Actions workflow runs daily at 00:17 UTC.
It reads the published releases in `Lineage-BBKey2/distribution`, including
prereleases, and records every uploaded asset's cumulative download counter.
It follows pagination for both releases and assets. GitHub-generated source
archives are not uploaded release assets and are not included.

## Output

- `data/downloads.csv`: append-only observation history (stored by atomic rewrite).
- `data/releases.json`: publication dates for recent-release selection and persistent per-release colours.
- `stats/downloads-30days-light.svg` and `stats/downloads-30days-dark.svg`: cumulative counters for the newest three ROM releases over the latest 30 UTC dates.
- `stats/downloads-total-light.svg` and `stats/downloads-total-dark.svg`: cumulative counters for all releases across the full recorded history.

The README shows the 30-day chart first, then the full-history chart. Each
has light and dark variants selected by GitHub's active theme using
`#gh-light-mode-only` and `#gh-dark-mode-only`. If GitHub follows the system
theme, chart selection follows it too. No Pages site or external chart service is
required. Each chart has separate panels for `lineage-*.zip` OTA files and
`LOS*.zip` installation bundles. Other filenames appear in a third panel if
present. `boot.img` and `recovery.img` are recorded in the CSV but excluded
from both charts. The recent chart includes observations in its date window
for only the three newest ROM release tags, ranked by GitHub publication
date, including prereleases. The same three tags are used across both panels. Lines and legends use
ascending numeric version order, independent of publication date. Each
release has one colour shared by both views and both themes, saved in
`data/releases.json` so future releases do not shift existing colours.
The full chart and CSV retain every release. An ordinary collection run
refreshes publication dates; chart-only regeneration uses the saved dates.
Tags with known publication dates take priority. If fewer than three have
known dates, first-observation dates are used to fill the remaining places,
with the tag name breaking ties.

## Operation

The workflow must be committed to `main`. Run it initially from
**Actions > Track ROM downloads > Run workflow**, selecting `main`.
The first successful run creates the CSV and both cumulative chart files.
Subsequent runs update them in one commit to `main`. The workflow never
edits the README itself. When upgrading from the version with a rate chart,
the workflow removes the tracked old chart images automatically. The job
uses `actions/setup-python@v6` (Node.js 24) and pins Ubuntu 24.04 rather than
using the moving `ubuntu-latest` label.

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
