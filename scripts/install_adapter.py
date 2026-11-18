#!/usr/bin/env python3
"""Link research-kit from this checkout into an OpenCode or Hermes profile."""

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("harness", choices=("opencode", "hermes"))
    harness = parser.parse_args().harness
    home = Path.home()
    repo = Path(__file__).resolve().parents[1]
    adapters = repo / "adapters"
    plugin = repo / "plugins" / "research-kit" / "skills"
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / "research-kit"
    links = {data / "core": plugin / "research-kit",
             data / "waste.sh": plugin / "waste" / "waste.sh"}
    if harness == "opencode":
        config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "opencode"
        for source in (adapters / harness / "commands").glob("*.md"):
            links[config / "commands" / source.name] = source
    else:
        config = Path(os.environ.get("HERMES_HOME") or home / ".hermes")
    skills = config / "skills"
    for name in ("research-kit", "team"):
        links[skills / name / "SKILL.md"] = adapters / "shared" / "skills" / name / "SKILL.md"
    references = skills / "team" / "references"
    links[references / "transport.md"] = adapters / harness / "transport.md"
    links[references / "architect.md"] = plugin / "team" / "architect-brief.md"

    for dest, source in links.items():
        if not source.exists():
            parser.exit(1, f"Missing source: {source}\n")
        for parent in dest.parents:
            if (parent.exists() or parent.is_symlink()) and not parent.is_dir():
                parser.exit(1, f"Not a directory: {parent}\n")
        if dest.is_symlink() and dest.readlink() == source:
            continue
        if dest.exists() or dest.is_symlink():
            parser.exit(1, f"Not replacing existing path: {dest}\n")
    for dest, source in links.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() and dest.readlink() == source:
            continue
        dest.symlink_to(source, target_is_directory=source.is_dir())
    print(f"Linked research-kit for {harness} in {config} (core: {data / 'core'}).")


if __name__ == "__main__":
    main()
