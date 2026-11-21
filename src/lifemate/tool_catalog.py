"""Load the tools available to one LifeMate sample."""

import json
from pathlib import Path


def load_available_tools(root: Path, split: str, context: dict) -> list:
    catalog_path = root / split / f"{split}_tools_catalog.json"

    with catalog_path.open(encoding="utf-8") as f:
        catalog = json.load(f)

    installed = context.get("installed_apps", {})

    allowed_names = set()

    for app in installed.values():
        allowed_names.update(app.get("tools", []))

    tools = []

    for app in catalog["apps"]:
        for tool in app["tools"]:
            # System clarification is available even without installation.
            if tool["name"] == "sys.ask_missing_info" or tool["name"] in allowed_names:
                tools.append(
                    {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool["parameters"],
                    }
                )

    return tools
