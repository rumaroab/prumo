from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.project = self.root / "checkout with spaces"
        self.project.mkdir()
        shutil.copyfile(Path(__file__).resolve().parents[1] / "start.sh", self.project / "start.sh")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "dirname").symlink_to(shutil.which("dirname"))
        self.log = self.root / "calls.log"
        self.env = {**os.environ, "PATH": str(self.bin), "STARTUP_LOG": str(self.log),
                    "FIRELINE_HOST": "127.0.0.1", "FIRELINE_PORT": "8000"}
        for tool in ("uv", "node", "npm", "cc"):
            stub = self.bin / tool
            stub.write_text(
                '#!/bin/sh\n'
                f'printf "%s\\n" "{tool}|$PWD|$UV_CACHE_DIR|$*" >> "$STARTUP_LOG"\n'
                'if [ "${FAIL_TOOL:-}" = "' + tool + '" ]; then exit 9; fi\n'
            )
            stub.chmod(0o755)

    def run_start(self):
        return subprocess.run(["/bin/sh", str(self.project / "start.sh")], cwd=self.root,
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_setup_runs_from_checkout_and_refreshes_existing_dependencies(self):
        (self.project / "frontend/node_modules").mkdir(parents=True)
        self.env.update(FIRELINE_HOST="0.0.0.0", FIRELINE_PORT="8123", NODE_ENV="production")
        result = self.run_start()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [line.split("|", 3) for line in self.log.read_text().splitlines()]
        self.assertEqual([(call[0], call[3]) for call in calls], [
            ("uv", "sync --locked"),
            ("npm", "--prefix frontend ci --include=dev --engine-strict"),
            ("npm", "--prefix frontend run build"),
            ("uv", "run --locked uvicorn backend.app.main:app --host 0.0.0.0 --port 8123 --proxy-headers"),
        ])
        self.assertTrue(all(call[1:3] == [str(self.project), str(self.project / ".uv-cache")]
                            for call in calls))
        self.assertIn("http://0.0.0.0:8123", result.stdout)

    def test_missing_prerequisite_explains_what_to_install(self):
        for tool in ("uv", "node", "npm", "cc"):
            with self.subTest(tool=tool):
                stub = self.bin / tool
                stub.rename(self.bin / "disabled")
                try:
                    result = self.run_start()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"Missing {tool}", result.stderr)
                    self.assertIn("README.md", result.stderr)
                    self.assertFalse(self.log.exists())
                finally:
                    (self.bin / "disabled").rename(stub)

    def test_dependency_failures_stop_before_starting_the_server(self):
        for tool in ("uv", "npm"):
            with self.subTest(tool=tool):
                self.env["FAIL_TOOL"] = tool
                result = self.run_start()
                self.assertEqual(result.returncode, 9)
                self.assertNotIn("uvicorn", self.log.read_text())
                self.log.unlink()


if __name__ == "__main__":
    unittest.main()
