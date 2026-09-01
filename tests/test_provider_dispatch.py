from __future__ import annotations

import unittest

from lib.config import _normalise_provider
from scripts import render_shot
from scripts.providers import bl


class ProviderDispatchTests(unittest.TestCase):
    def test_public_provider_aliases_are_stable(self) -> None:
        cases = {
            "wan": "wan_cli",
            "wan-cli": "wan_cli",
            "bl": "bl",
            "happyhorse": "bl",
            "seedance": "seedance2",
            "seedance2": "seedance2",
        }
        for public_name, module_name in cases.items():
            with self.subTest(public_name=public_name):
                self.assertEqual(
                    render_shot._normalise_provider_name(public_name), module_name
                )

    def test_config_keeps_public_provider_names(self) -> None:
        self.assertEqual(_normalise_provider("wan"), "wan-cli")
        self.assertEqual(_normalise_provider("happyhorse"), "bl")
        self.assertEqual(_normalise_provider("seedance"), "seedance2")

    def test_every_bundled_provider_loads(self) -> None:
        for module_name in ("wan_cli", "bl", "seedance2"):
            with self.subTest(module_name=module_name):
                provider = render_shot._load_provider(module_name)
                self.assertTrue(callable(provider.render))

    def test_bl_clamps_to_happyhorse_duration_range(self) -> None:
        self.assertEqual(bl._clamp_duration(2), 3)
        self.assertEqual(bl._clamp_duration(8), 8)
        self.assertEqual(bl._clamp_duration(30), 15)

if __name__ == "__main__":
    unittest.main()
