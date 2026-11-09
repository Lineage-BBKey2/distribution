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


def collect(repository, history, release_metadata=None):
    # Complete every API request before changing any saved files.
    assets = []
    for release in get_all(repository, "releases"):
        if not release["draft"]:
            if release_metadata is not None:
                release_metadata[release["tag_name"]] = {
                    "published_at": release["published_at"],
                    "id": release["id"],
                }
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


def select_recent_tags(history, release_metadata):
    first_seen = {}
    for row in history:
        if category(row["asset"]) == "Other attachments":
            continue
        timestamp = parse_time(row["observed_at"])
        first_seen[row["tag"]] = min(timestamp, first_seen.get(row["tag"], timestamp))

    def rank(tag):
        published = release_metadata.get(tag, {}).get("published_at")
        return (bool(published), parse_time(published) if published else first_seen[tag], tag)

    return set(sorted(first_seen, key=rank, reverse=True)[:3])


def render(history, directory, release_metadata=None):
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

    tags = sorted({row["tag"] for row in history})
    recent_tags = select_recent_tags(history, release_metadata or {})
    latest = max((parse_time(row["observed_at"]) for row in history), default=None)
    earliest = min((parse_time(row["observed_at"]) for row in history), default=None)
    recent_start = recent_end = None
    if latest is not None:
        midnight = latest.replace(hour=0, minute=0, second=0, microsecond=0)
        first = earliest.replace(hour=0, minute=0, second=0, microsecond=0)
        recent_start = max(first, midnight - timedelta(days=29))
        recent_end = midnight + timedelta(days=1)

    themes = {
        "light": {"background": "#ffffff", "text": "#1f2328", "grid": "#d0d7de",
                  "muted": "#59636e", "palette": ["#0969da", "#bc4c00", "#1a7f37", "#8250df", "#cf222e", "#0550ae", "#953800", "#0a3069", "#6639ba", "#116329"]},
        "dark": {"background": "#0d1117", "text": "#e6edf3", "grid": "#30363d",
                 "muted": "#9198a1", "palette": ["#58a6ff", "#ffa657", "#7ee787", "#d2a8ff", "#ff7b72", "#79c0ff", "#ffc680", "#a5d6ff", "#e2c5ff", "#aff5b4"]},
    }
    for mode in ("30days", "total"):
        visible_groups = []
        for rows in groups.values():
            if mode == "30days" and rows[-1]["tag"] not in recent_tags:
                continue
            visible = rows if mode == "total" else [
                row for row in rows
                if recent_start <= parse_time(row["observed_at"]) < recent_end
            ]
            if visible:
                visible_groups.append(visible)
        shown_panels = [panel for panel in panels
                        if panel != "Other attachments" or any(
                            category(rows[-1]["asset"]) == panel for rows in visible_groups)]

        for theme_name, theme in themes.items():
            settings = {
                "font.family": "DejaVu Sans", "font.size": 10,
                "svg.hashsalt": "rom-download-statistics",
                "figure.facecolor": theme["background"], "axes.facecolor": theme["background"],
                "text.color": theme["text"], "axes.labelcolor": theme["text"],
                "axes.edgecolor": theme["muted"], "xtick.color": theme["text"],
                "ytick.color": theme["text"], "grid.color": theme["grid"],
            }
            with plt.rc_context(settings):
                colors = {tag: theme["palette"][i % len(theme["palette"])]
                          for i, tag in enumerate(tags)}
                fig, axes = plt.subplots(len(shown_panels), 1, figsize=(12, 4.5 * len(shown_panels)))
                title = ("Cumulative ROM downloads — full history" if mode == "total"
                         else "Cumulative ROM downloads — latest 30 days / newest 3 releases")
                fig.suptitle(title, fontsize=16, fontweight="bold", y=0.99)
                for ax, panel in zip(axes, shown_panels):
                    selected = [rows for rows in visible_groups if category(rows[-1]["asset"]) == panel]
                    duplicates = Counter(rows[-1]["tag"] for rows in selected)
                    for rows in sorted(selected, key=lambda rows: rows[-1]["tag"]):
                        tag = rows[-1]["tag"]
                        label = tag if duplicates[tag] == 1 else f"{tag} / asset {rows[-1]['asset_id']}"
                        xs = [parse_time(row["observed_at"]) for row in rows]
                        ys = [int(row["total"]) for row in rows]
                        ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.6,
                                color=colors[tag], label=label)
                    ax.set_title(panel, loc="left", fontweight="bold")
                    ax.set_ylabel("Cumulative downloads")
                    ax.set_xlabel("Observation time (UTC)")
                    ax.set_ylim(bottom=0)
                    ax.grid(axis="y", alpha=0.6)
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
                    if selected:
                        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
                    else:
                        ax.text(0.5, 0.5, "No matching observations in this window",
                                transform=ax.transAxes, ha="center", va="center")
                updated = latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "No observations yet"
                fig.text(0.01, 0.012, f"Last observation: {updated}", fontsize=9, color=theme["muted"])
                fig.tight_layout(rect=(0, 0.035, 1, 0.965))
                destination = directory / f"downloads-{mode}-{theme_name}.svg"
                content = io.StringIO()
                fig.savefig(content, format="svg", metadata={"Date": None}, facecolor=theme["background"])
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
    metadata_path = ROOT / "data/releases.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    if not args.render_only:
        history += collect(args.repository, history, metadata)
    render(history, ROOT / "stats", metadata)
    if not args.render_only:
        save_history(path, history)
        temporary = metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(metadata_path)
    print(f"Rendered two charts in light and dark themes from {len(history)} recorded asset observations")


if __name__ == "__main__":
    main()
