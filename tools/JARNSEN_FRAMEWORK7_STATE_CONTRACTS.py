"""Explicit state contracts for the Framework7 headless service bridge.

The redesign owns concrete runtime state.  Historical compatibility patches once
allowed a method and a mapping to share the same attribute name, which can hide a
real state-ownership regression until a later ``.get`` call fails.  Materialize a
legacy zero-argument mapping provider once, then keep only concrete mapping state.
Anything else is a startup error with the offending attribute named explicitly.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_REQUIRED_MAPPING_STATES = (
    "node_sync_state_v2132",
    "config_profile_store",
)


def _concrete_mapping_state(name: str, value: Any) -> dict[Any, Any]:
    """Return concrete mapping state or fail with a diagnostic type error."""

    if isinstance(value, dict):
        return value
    if isinstance(value, Mapping):
        return dict(value)

    if callable(value):
        try:
            resolved = value()
        except TypeError as exc:
            raise RuntimeError(
                f"Framework7 service state '{name}' is a callable requiring arguments; "
                "a concrete mapping is required"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Framework7 service state '{name}' failed while materializing its mapping: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if isinstance(resolved, dict):
            return resolved
        if isinstance(resolved, Mapping):
            return dict(resolved)
        raise RuntimeError(
            f"Framework7 service state '{name}' callable returned "
            f"{type(resolved).__name__}; a mapping is required"
        )

    raise RuntimeError(
        f"Framework7 service state '{name}' has invalid type "
        f"{type(value).__name__}; a mapping is required"
    )


def enforce_service_state_contracts(tool: Any) -> None:
    """Make bridge-owned mapping state concrete before any feature uses ``.get``."""

    for name in _REQUIRED_MAPPING_STATES:
        if not hasattr(tool, name):
            raise RuntimeError(
                f"Framework7 service state '{name}' is missing; headless initialization is incomplete"
            )
        value = getattr(tool, name)
        concrete = _concrete_mapping_state(name, value)
        if concrete is not value:
            setattr(tool, name, concrete)

    profile_store = tool.config_profile_store
    profiles = profile_store.get("profiles")
    if not isinstance(profiles, list):
        raise RuntimeError(
            "Framework7 service state 'config_profile_store.profiles' must be a list"
        )
