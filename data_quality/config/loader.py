"""
Load validation rules and thresholds from YAML (R-DQ6, Chapter 4 Section 4.8.1).

The thresholds and rule parameters are defined in
``data_quality/config/rules.yaml`` and loaded at runtime so that batch mode,
incremental mode, the live API and the dashboard all enforce the identical rule
set and the dashboard's display targets stay synchronised with the engine's
pass/fail logic.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).resolve().parent / "rules.yaml"


def load_config(path: str | Path = _CONFIG_PATH) -> dict:
    """Return the parsed configuration (thresholds, rules, sensitivity).

    Args:
        path: Override for the rules.yaml location.

    Returns:
        dict: The full configuration.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def get_rule_params(rule_id: str) -> dict:
    """Return the configuration block for a given rule.

    Args:
        rule_id: Rule key such as ``"r14_progress_mismatch"``.

    Returns:
        dict: The rule's parameters, or an empty dict when absent.
    """
    config = load_config()
    return config.get("rules", {}).get(rule_id.lower(), {})


def load_rules(path: str | Path = _CONFIG_PATH) -> dict:
    """Alias for :func:`load_config`, retained for callers that used the old name."""
    return load_config(path)


def rule_definitions(config: dict) -> list[dict]:
    """Return the per-rule catalogue entries (dimension, view, severity)."""
    return config.get("rule_catalogue", [])


def rule_dimensions(config: dict) -> dict[str, str]:
    """Map rule id -> dimension name."""
    return {r["id"]: r["dimension"] for r in rule_definitions(config)}


def rule_targets(config: dict) -> dict[str, float]:
    """Map dimension name -> target threshold."""
    return dict(config.get("thresholds", {}))


def rules_by_view(config: dict, view: str) -> list[dict]:
    """Return catalogue rules assigned to a given evaluation view."""
    return [r for r in rule_definitions(config) if r["evaluation_view"] == view]
