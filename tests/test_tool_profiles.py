"""Server-enforced compact tool profile contracts."""

from __future__ import annotations

import unittest

from src.termuinator.schema import PUBLIC_TOOL_NAMES
from src.termuinator.tool_profiles import TOOL_PROFILES, resolve_tool_profile


class CompactToolProfileTests(unittest.TestCase):
    def test_interactive_is_the_complete_frozen_surface(self) -> None:
        self.assertEqual(resolve_tool_profile("interactive"), PUBLIC_TOOL_NAMES)

    def test_observer_removes_page_mutation_tools_but_keeps_browse_lifecycle(self) -> None:
        observer = resolve_tool_profile("observer")

        self.assertEqual(len(observer), len(set(observer)))
        self.assertTrue(set(observer) < set(PUBLIC_TOOL_NAMES))
        self.assertNotIn("browser_act", observer)
        self.assertNotIn("browser_tabs", observer)
        for required in (
            "browser_session_start",
            "browser_session_status",
            "browser_session_stop",
            "browser_navigate",
            "browser_observe",
            "browser_screenshot",
            "browser_artifact_read",
            "browser_permissions",
            "browser_trace",
        ):
            self.assertIn(required, observer)

    def test_profile_names_and_unknown_profile_are_closed(self) -> None:
        self.assertEqual(set(TOOL_PROFILES), {"observer", "interactive"})
        with self.assertRaisesRegex(ValueError, "tool profile"):
            resolve_tool_profile("unsafe-all")


if __name__ == "__main__":
    unittest.main()
