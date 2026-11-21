"""Format allowed tools for language-model prompts."""


def compact_tools(tools: list[dict]) -> list[dict]:
    """Retain names, parameter types, requirements, and key constraints."""
    result = []

    for tool in tools:
        parameters = tool.get("parameters", {})
        properties = {}

        for name, spec in parameters.get("properties", {}).items():
            entry = {
                "type": spec.get("type", "any"),
            }

            for key in ("enum", "x-ref", "x-match"):
                if key in spec:
                    entry[key] = spec[key]

            properties[name] = entry

        compact = {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "properties": properties,
            "required": parameters.get("required", []),
        }

        if "x-one-of" in parameters:
            compact["x-one-of"] = parameters["x-one-of"]

        result.append(compact)

    return result


def compact_tools_with_descriptions(tools: list[dict]) -> list[dict]:
    """Compact schemas while preserving parameter descriptions."""
    result = compact_tools(tools)

    for original, compact in zip(tools, result, strict=True):
        original_properties = original.get("parameters", {}).get("properties", {})

        for name, spec in original_properties.items():
            if "description" in spec:
                compact["properties"][name]["description"] = spec["description"]

    return result
