"""Nothing secret may reach a commit.

The repository is public, and the AQICN token now has three ways to leak:
a literal in the polling URL, a value typed into the preview's Custom Fields
picker (which rewrites the committed .trmnlp.yml), and an env file sitting in
the working tree. Each gets a guard.
"""

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return [ROOT / f for f in out.split("\0") if f]


class TestNoSecretsCommitted(unittest.TestCase):
    def test_env_files_are_ignored(self):
        for name in (".env", ".env.local"):
            r = subprocess.run(["git", "check-ignore", name], cwd=ROOT, capture_output=True)
            self.assertEqual(r.returncode, 0, "%s is not gitignored" % name)

    def test_no_env_file_is_tracked(self):
        for f in tracked_files():
            self.assertFalse(f.name.startswith(".env") and f.name != ".env.example",
                             "%s is tracked" % f.name)

    def test_polling_url_interpolates_the_token(self):
        settings = (ROOT / "src" / "settings.yml").read_text()
        waqi = [l for l in settings.splitlines() if "api.waqi.info" in l]
        self.assertEqual(len(waqi), 1, "expected one aqicn URL")
        self.assertIn("token={{ aqicn_token }}", waqi[0],
                      "the token must come from the custom field, never be literal")

    def test_dev_config_reads_the_token_from_the_environment(self):
        cfg = (ROOT / ".trmnlp.yml").read_text()
        m = re.search(r"aqicn_token:\s*(.+)", cfg)
        self.assertIsNotNone(m, "aqicn_token missing from .trmnlp.yml")
        self.assertIn("env.", m.group(1),
                      ".trmnlp.yml is committed and `serve` rewrites it from the "
                      "picker, so it must never hold the value itself")

    def test_no_tracked_file_holds_a_token_shaped_string(self):
        """A WAQI token is a long lowercase hex string."""
        pattern = re.compile(r"\b[0-9a-f]{24,}\b")
        allow = {"tools/data/sgp-adm0.geojson"}
        for f in tracked_files():
            rel = f.relative_to(ROOT).as_posix()
            if rel in allow or f.suffix in {".png", ".jpg"}:
                continue
            try:
                text = f.read_text(errors="ignore")
            except Exception:
                continue
            for hit in pattern.findall(text):
                self.fail("%s contains a token-shaped string %r" % (rel, hit[:8] + "..."))

    def test_fixtures_carry_no_token(self):
        for f in (ROOT / "fixtures").glob("*.json"):
            self.assertNotIn("token", f.read_text().lower(),
                             "%s mentions a token" % f.name)


if __name__ == "__main__":
    unittest.main()
