#!/usr/bin/env python3
"""Unit tests for the configuration-driven TSMC40 gm/ID runner."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import run_tsmc40 as runner


BASE_DIR = Path(__file__).resolve().parent


class ConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = runner.load_profiles(BASE_DIR / "profiles.json")

    def test_builtin_profiles_and_point_counts(self) -> None:
        self.assertEqual(set(self.profiles), {"1v1", "2v5"})
        self.assertEqual(self.profiles["1v1"].expected_points, 221)
        self.assertEqual(self.profiles["2v5"].expected_points, 251)

    def test_numeric_profile_names_and_posix_pdk_paths_are_valid(self) -> None:
        profile = self.profiles["1v1"]
        self.assertEqual(profile.profile, "1v1")
        self.assertTrue(profile.pdk_model.startswith("/"))
        runner.validate_config(profile)

    def test_invalid_configurations_are_rejected(self) -> None:
        profile = self.profiles["2v5"]
        invalid = (
            replace(profile, vgs_step_v=0.03),
            replace(profile, nmos_model="nch-unsafe"),
            replace(profile, pdk_model=r"C:\PDKS\model.scs"),
            replace(profile, vds_v=(1.25, 1.25)),
        )
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                runner.validate_config(config)


class GeneratedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = runner.load_profiles(BASE_DIR / "profiles.json")["2v5"]
        cls.devices = runner.build_devices(cls.profile)

    def test_dynamic_netlist_uses_profile_values(self) -> None:
        self.assertEqual(len(self.devices), 6)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "characterize.scs"
            runner.write_netlist(path, self.profile, self.devices)
            text = path.read_text(encoding="utf-8")

        self.assertIn(
            'include "/PDKS/TSMC40nm/models/spectre/toplevel.scs" section=top_tt',
            text,
        )
        self.assertIn("nch_25", text)
        self.assertIn("pch_25", text)
        self.assertIn("l=2.7e-07", text)
        self.assertIn("dc1 dc param=VSWEEP start=0 stop=2.5 step=0.01", text)

    def test_gnuplot_families_have_valid_continuations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_paths = [(vds, root / f"{vds}.csv") for vds in self.profile.vds_v]
            script = root / "plot.gnuplot"
            runner.create_plot_script(
                script,
                root / "plot.svg",
                self.profile,
                self.profile.nmos_model,
                "nmos",
                csv_paths,
            )
            text = script.read_text(encoding="utf-8")

        self.assertIn("\\\n    '", text)
        self.assertNotIn("\\\n+", text)


if __name__ == "__main__":
    unittest.main()
