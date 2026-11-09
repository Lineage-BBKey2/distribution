#!/usr/bin/env python3
"""Snapshot release-asset counters and render README charts.

Requires GitHub CLI (gh) for collection and matplotlib for rendering.
The CSV schema is compatible with the original CSV-only workflow.
"""

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, NullFormatter


ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "observed_at", "tag", "asset", "asset_id", "total",
    "previous_observed_at", "new_downloads",
]
EXCLUDED_CHART_ASSETS = {"boot.img", "recovery.img"}


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError(f"Timestamp must include a timezone: {value}")
    return result.astimezone(timezone.utc)


def read_history(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"Unexpected CSV columns in {path}; history was not changed")
        rows = list(reader)
    for row in rows:
        parse_time(row["observed_at"])
        int(row["total"])
    return rows


def get_all(repository, endpoint):
    result = subprocess.check_output(
        ["gh", "api", "--paginate", "--slurp",
         f"repos/{repository}/{endpoint}?per_page=100"],
        text=True,
    )
    return [item for page in json.loads(result) for item in page]


def collect(repository, history):
    # Complete every API request before changing any saved files.
    assets = []
    for release in get_all(repository, "releases"):
        if not release["draft"]:
            for asset in get_all(repository, f"releases/{release['id']}/assets"):
                assets.append((release["tag_name"], asset))
    if not assets:
        raise RuntimeError("No published release assets found; existing history was not changed")

    previous = {}
    for row in sorted(history, key=lambda r: parse_time(r["observed_at"])):
        previous[row["asset_id"]] = row
    observed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    result = []
    for tag, asset in assets:
        asset_id = str(asset["id"])
        total = asset["download_count"]
        old = previous.get(asset_id)
        difference = total - int(old["total"]) if old else -1
        result.append(dict(zip(FIELDS, [
            observed, tag, asset["name"], asset_id, total,
            old["observed_at"] if old else "",
            difference if difference >= 0 else "",
        ])))
    return result


def save_history(path, history):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(history)
    temporary.replace(path)


def category(name):
    lower = name.lower()
    if lower.startswith("lineage-") and lower.endswith(".zip"):
        return "OTA ROM ZIPs"
    if lower.startswith("los") and lower.endswith(".zip"):
        return "Installation bundles"
    return "Other attachments"


def render(history, directory):
    directory.mkdir(parents=True, exist_ok=True)
    # Keep these assets in the CSV, but omit them from both charts.
    history = [row for row in history
               if row["asset"].casefold() not in EXCLUDED_CHART_ASSETS]
    groups = defaultdict(list)
    for row in history:
        groups[row["asset_id"]].append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: parse_time(r["observed_at"]))

    panels = ["OTA ROM ZIPs", "Installation bundles"]
    if any(category(rows[-1]["asset"]) == "Other attachments" for rows in groups.values()):
        panels.append("Other attachments")

    # Stable tags/colors; include all recorded assets, including deleted ones.
    tags = sorted({row["tag"] for row in history})
    colors = {tag: plt.get_cmap("tab20")(i % 20) for i, tag in enumerate(tags)}
    latest = max((parse_time(row["observed_at"]) for row in history), default=None)
    earliest = min((parse_time(row["observed_at"]) for row in history), default=None)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "svg.hashsalt": "rom-download-statistics",
    })

    # Include the latest observed UTC date and its preceding 29 dates.
    # The rolling window changes the displayed range, never the saved CSV.
    recent_start = None
    recent_end = None
    if latest is not None:
        latest_midnight = latest.replace(hour=0, minute=0, second=0, microsecond=0)
        first_midnight = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
        recent_start = max(first_midnight, latest_midnight - timedelta(days=29))
        recent_end = latest_midnight + timedelta(days=1)

    for mode in ("total", "30days"):
        fig, axes = plt.subplots(len(panels), 1, figsize=(12, 4.5 * len(panels)))
        title = ("Cumulative ROM downloads — full history" if mode == "total"
                 else "Cumulative ROM downloads — latest 30 days")
        fig.suptitle(title, fontsize=18, fontweight="bold", y=0.99)

        for ax, panel in zip(axes, panels):
            selected = []
            for rows in groups.values():
                if category(rows[-1]["asset"]) != panel:
                    continue
                visible = rows if mode == "total" else [
                    row for row in rows
                    if recent_start <= parse_time(row["observed_at"]) < recent_end
                ]
                if visible:
                    selected.append(visible)
            duplicates = Counter(rows[-1]["tag"] for rows in selected)
            plotted = 0
            for rows in sorted(selected, key=lambda rows: rows[-1]["tag"]):
                tag = rows[-1]["tag"]
                label = tag
                if duplicates[tag] > 1:
                    label += f" / asset {rows[-1]['asset_id']}"
                xs, ys = [], []
                for row in rows:
                    observed = parse_time(row["observed_at"])
                    xs.append(observed)
                    ys.append(int(row["total"]))
                if xs:
                    ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.6,
                            color=colors[tag], label=label)
                    plotted += 1

            ax.set_title(panel, loc="left", fontweight="bold")
            ax.set_ylabel("Cumulative downloads")
            ax.set_xlabel("Observation time (UTC)")
            ax.set_ylim(bottom=0)
            ax.grid(axis="y", alpha=0.22)
            ax.spines[["top", "right"]].set_visible(False)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
            if earliest is not None:
                if mode == "total":
                    padding = max((latest - earliest) / 30, timedelta(hours=1))
                    ax.set_xlim(earliest - padding, latest + padding)
                else:
                    ax.set_xlim(recent_start, recent_end)
            else:
                ax.set_xticks([])
                ax.xaxis.set_major_formatter(NullFormatter())
            if plotted:
                ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
            else:
                message = ("No matching observations in this window" if mode == "30days"
                           else "No matching assets observed yet")
                ax.text(0.5, 0.5, message, transform=ax.transAxes, ha="center", va="center")

        note = "File downloads, not unique users or installations. No history is inferred before collection began."
        if mode == "30days":
            note = "Latest 30 UTC calendar dates; values remain lifetime totals. Complete history is retained in the CSV."
        updated = latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "No observations yet"
        fig.text(0.01, 0.012, f"{note}\nLast observation: {updated}", fontsize=9, color="#555555")
        fig.tight_layout(rect=(0, 0.055, 1, 0.965))
        destination = directory / f"downloads-{mode}.svg"
        # No changing SVG generation timestamp, and write atomically.
        content = io.StringIO()
        fig.savefig(content, format="svg", metadata={"Date": None}, facecolor="white")
        temporary = destination.with_suffix(".svg.tmp")
        temporary.write_text(content.getvalue(), encoding="utf-8")
        temporary.replace(destination)
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="Lineage-BBKey2/distribution")
    parser.add_argument("--render-only", action="store_true", help="Regenerate charts from the CSV without collecting")
    args = parser.parse_args()
    path = ROOT / "data/downloads.csv"
    history = read_history(path)
    if not args.render_only:
        history += collect(args.repository, history)
    render(history, ROOT / "stats")
    if not args.render_only:
        save_history(path, history)
    print(f"Rendered two charts from {len(history)} recorded asset observations")


if __name__ == "__main__":
    main()
