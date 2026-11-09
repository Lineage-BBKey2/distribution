#!/usr/bin/env python3
"""Snapshot release-asset counters and render README charts.

Requires GitHub CLI (gh) for collection and matplotlib for rendering.
The CSV schema is compatible with the original CSV-only workflow.
"""

import argparse
import colorsys
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import io
import json
import math
from pathlib import Path
import re
import subprocess

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, NullFormatter
from matplotlib.legend import Legend
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[1]
FIELDS = [
    "observed_at", "tag", "asset", "asset_id", "total",
    "previous_observed_at", "new_downloads",
]
EXCLUDED_CHART_ASSETS = {"boot.img", "recovery.img"}
RELEASE_PALETTE = [
    "#2f81f7", "#d97706", "#2da44e", "#a371f7", "#e5534b", "#1b9e9e",
    "#c964a6", "#9a8b16", "#848d97", "#7957d5", "#b76b35", "#4899ab",
]


def version_sort_key(tag):
    natural = tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                    for part in re.split(r"(\d+)", tag) if part)
    return (0 if tag.startswith("2026") else 1, natural)


def release_colors(tags, release_metadata):
    # Retain assignments even when a release leaves the recent chart or a
    # newly published tag sorts before an existing tag.
    used = {entry["color"].lower() for entry in release_metadata.values()
            if re.fullmatch(r"#[0-9a-fA-F]{6}", entry.get("color", ""))}
    colors = {}
    candidate_index = 0
    for tag in sorted(tags, key=version_sort_key):
        entry = release_metadata.setdefault(tag, {})
        color = entry.get("color", "")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            while True:
                if candidate_index < len(RELEASE_PALETTE):
                    color = RELEASE_PALETTE[candidate_index]
                else:
                    hue = ((candidate_index - len(RELEASE_PALETTE)) * 0.61803398875) % 1
                    rgb = colorsys.hls_to_rgb(hue, 0.5, 0.65)
                    color = "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)
                candidate_index += 1
                if color.lower() not in used:
                    break
            entry["color"] = color
        colors[tag] = color.lower()
        used.add(color.lower())
    return colors


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
                release_metadata.setdefault(release["tag_name"], {}).update({
                    "published_at": release["published_at"],
                    "id": release["id"],
                })
            for asset in get_all(repository, f"releases/{release['id']}/assets"):
                if release_metadata is not None and asset.get("created_at"):
                    release_metadata[release["tag_name"]].setdefault(
                        "asset_created_at", {})[str(asset["id"])] = asset["created_at"]
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


def shared_history_legend(fig, handles_by_tag):
    """Fit one row-major, wrapping legend below the full-history panels."""
    if not handles_by_tag:
        fig.tight_layout(rect=(0, 0.035, 1, 0.965))
        return

    tags = sorted(handles_by_tag, key=version_sort_key)
    entries = [(handles_by_tag[tag], tag) for tag in tags]
    options = dict(frameon=False, fontsize=10, handlelength=2,
                   columnspacing=1.4, labelspacing=0.6,
                   borderpad=0, borderaxespad=0)
    renderer = fig.canvas.get_renderer()
    available_width = (fig.get_figwidth() - 0.8) * fig.dpi
    for columns in range(min(len(entries), 12), 0, -1):
        rows = (len(entries) + columns - 1) // columns
        padding = (Line2D([], [], linestyle="none", marker="", alpha=0), "")
        padded = entries + [padding] * (rows * columns - len(entries))
        # Matplotlib fills columns first. Transpose a padded row-major grid
        # so versions actually read left-to-right before starting a new row.
        ordered = [padded[row * columns + column]
                   for column in range(columns) for row in range(rows)]
        handles, labels = zip(*ordered)
        probe = Legend(fig, handles, labels, loc="lower center",
                       ncols=columns, **options)
        extent = probe.get_window_extent(renderer)
        if extent.width <= available_width:
            break

    legend_height = extent.height / fig.dpi
    fig.set_size_inches(fig.get_figwidth(), fig.get_figheight() + legend_height + 0.45)
    height = fig.get_figheight()
    fig.legend(handles, labels, loc="lower center", ncols=columns,
               bbox_to_anchor=(0.5, 0.45 / height),
               bbox_transform=fig.transFigure, **options)
    # Reserve physical space for the legend, a gap, and the observation
    # timestamp. Added rows increase image height instead of overlapping.
    fig.tight_layout(rect=(0, (0.45 + legend_height + 0.25) / height, 1, 0.965))


def combined_daily_series(history, release_metadata):
    """Combine counter increases over matching snapshot intervals."""
    snapshots = defaultdict(dict)
    for row in history:
        if row["asset"].casefold() not in EXCLUDED_CHART_ASSETS:
            snapshots[parse_time(row["observed_at"])][row["asset_id"]] = row
    births = {}
    for entry in release_metadata.values():
        births.update(entry.get("asset_created_at", {}))

    observed = sorted(snapshots)
    xs, rates = [], []
    for start, end in zip(observed, observed[1:]):
        previous, current = snapshots[start], snapshots[end]
        # A removed asset's final increase is unknown. Leave that interval
        # blank rather than silently understating the combined download rate.
        complete = not (previous.keys() - current.keys())
        increase = 0
        for asset_id, row in current.items():
            if asset_id in previous:
                delta = int(row["total"]) - int(previous[asset_id]["total"])
                if delta < 0:
                    complete = False
                else:
                    increase += delta
            else:
                created = births.get(asset_id)
                if created and start < parse_time(created) <= end:
                    # This asset did not exist at the previous observation:
                    # its zero baseline is known, so count initial downloads.
                    increase += int(row["total"])
                else:
                    complete = False
        xs.append(end)
        rates.append(increase * 86400 / (end - start).total_seconds()
                     if complete else math.nan)
    return xs, rates


def render_daily(history, directory, metadata, themes, earliest, latest):
    xs, rates = combined_daily_series(history, metadata)
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
            fig, ax = plt.subplots(figsize=(12, 4.5))
            fig.suptitle("Combined downloads per day — full history",
                         fontsize=16, fontweight="bold", y=0.99)
            if xs:
                ax.plot(xs, rates, color="#2f81f7", marker="o", markersize=3, linewidth=1.6)
            if not any(math.isfinite(value) for value in rates):
                ax.text(0.5, 0.5, "No complete download intervals recorded yet",
                        transform=ax.transAxes, ha="center", va="center")
            ax.set_ylabel("Downloads/day (interval average)")
            ax.set_xlabel("Observation time (UTC)")
            ax.set_ylim(bottom=0)
            ax.grid(axis="y", alpha=0.6)
            ax.spines[["top", "right"]].set_visible(False)
            locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
            ax.xaxis.set_major_locator(locator)
            ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator, tz=timezone.utc))
            if earliest is not None:
                padding = max((latest - earliest) / 30, timedelta(hours=1))
                ax.set_xlim(earliest - padding, latest + padding)
            else:
                ax.set_xticks([])
                ax.xaxis.set_major_formatter(NullFormatter())
            updated = latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "No observations yet"
            fig.text(0.01, 0.012, f"Last observation: {updated}", fontsize=9, color=theme["muted"])
            fig.tight_layout(rect=(0, 0.06, 1, 0.95))
            destination = directory / f"downloads-daily-{theme_name}.svg"
            content = io.StringIO()
            fig.savefig(content, format="svg", metadata={"Date": None}, facecolor=theme["background"])
            temporary = destination.with_suffix(".svg.tmp")
            temporary.write_text(content.getvalue(), encoding="utf-8")
            temporary.replace(destination)
            plt.close(fig)


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

    tags = sorted({row["tag"] for row in history}, key=version_sort_key)
    metadata = release_metadata if release_metadata is not None else {}
    colors = release_colors(tags, metadata)
    recent_tags = select_recent_tags(history, metadata)
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
                  "muted": "#59636e"},
        "dark": {"background": "#0d1117", "text": "#e6edf3", "grid": "#30363d",
                 "muted": "#9198a1"},
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
                fig, axes = plt.subplots(len(shown_panels), 1, figsize=(12, 4.5 * len(shown_panels)))
                title = ("Cumulative ROM downloads — full history" if mode == "total"
                         else "Cumulative ROM downloads — last 30 days / newest 3 releases")
                fig.suptitle(title, fontsize=16, fontweight="bold", y=0.99)
                shared_handles = {}
                for ax, panel in zip(axes, shown_panels):
                    selected = [rows for rows in visible_groups if category(rows[-1]["asset"]) == panel]
                    duplicates = Counter(rows[-1]["tag"] for rows in selected)
                    for rows in sorted(selected, key=lambda rows: (
                            version_sort_key(rows[-1]["tag"]), rows[-1]["asset"].casefold(),
                            int(rows[-1]["asset_id"]))):
                        tag = rows[-1]["tag"]
                        label = tag if duplicates[tag] == 1 else f"{tag} / asset {rows[-1]['asset_id']}"
                        xs = [parse_time(row["observed_at"]) for row in rows]
                        ys = [int(row["total"]) for row in rows]
                        line, = ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.6,
                                        color=colors[tag], label=label)
                        shared_handles.setdefault(tag, line)
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
                    if selected and mode != "total":
                        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), frameon=False)
                    elif not selected:
                        ax.text(0.5, 0.5, "No matching observations in this window",
                                transform=ax.transAxes, ha="center", va="center")
                updated = latest.strftime("%Y-%m-%d %H:%M UTC") if latest else "No observations yet"
                if mode == "total":
                    shared_history_legend(fig, shared_handles)
                    footer_y = 0.12 / fig.get_figheight()
                else:
                    fig.tight_layout(rect=(0, 0.035, 1, 0.965))
                    footer_y = 0.012
                fig.text(0.01, footer_y, f"Last observation: {updated}", fontsize=9, color=theme["muted"])
                destination = directory / f"downloads-{mode}-{theme_name}.svg"
                content = io.StringIO()
                fig.savefig(content, format="svg", metadata={"Date": None}, facecolor=theme["background"])
                temporary = destination.with_suffix(".svg.tmp")
                temporary.write_text(content.getvalue(), encoding="utf-8")
                temporary.replace(destination)
                plt.close(fig)

    render_daily(history, directory, metadata, themes, earliest, latest)


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
    print(f"Rendered three charts in light and dark themes from {len(history)} recorded asset observations")


if __name__ == "__main__":
    main()
