"""Closed, backend-neutral browser wait condition evaluation."""

from __future__ import annotations

from ..contracts import (
    Observation,
    WaitCondition,
    WaitDownloadCondition,
    WaitNavigationCondition,
    WaitRefStateCondition,
    WaitTextCondition,
    WaitUrlCondition,
)


_WAIT_CONDITION_TYPES = (
    WaitUrlCondition,
    WaitTextCondition,
    WaitRefStateCondition,
    WaitNavigationCondition,
    WaitDownloadCondition,
)


def is_wait_condition(value: object) -> bool:
    """Return whether a value belongs to the frozen wait-condition union."""

    return isinstance(value, _WAIT_CONDITION_TYPES)


def evaluate_wait(condition: WaitCondition, observation: Observation) -> bool:
    """Evaluate one closed page condition against a bounded observation."""

    if not is_wait_condition(condition):
        raise TypeError("condition must belong to the frozen wait union")
    if not isinstance(observation, Observation):
        raise TypeError("wait evaluation requires an Observation")
    if isinstance(condition, WaitUrlCondition):
        return observation.url == condition.url
    if isinstance(condition, WaitTextCondition):
        found = condition.text in observation.text
        if condition.present:
            return found
        return not found and not observation.text_truncated
    if isinstance(condition, WaitRefStateCondition):
        element = next(
            (
                item
                for item in observation.interactive_elements
                if item.ref == condition.target_ref
            ),
            None,
        )
        if condition.state == "hidden":
            return element is None or not element.visible
        if element is None:
            return False
        if condition.state == "visible":
            return element.visible
        if condition.state == "enabled":
            return element.enabled
        return not element.enabled
    if isinstance(condition, WaitNavigationCondition):
        return observation.page_revision != condition.from_revision
    if isinstance(condition, WaitDownloadCondition):
        raise ValueError("download conditions require the download lifecycle")
    raise AssertionError("wait condition union is incomplete")


__all__ = ["evaluate_wait", "is_wait_condition"]
