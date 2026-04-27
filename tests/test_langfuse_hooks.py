from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = ROOT / "scripts" / "langfuse-hook.sh"
STOP_SCRIPT = ROOT / "scripts" / "langfuse-stop-hook.sh"


class LangfuseHookScriptsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.temp_dir.name)
        self.capture_file = self.workdir / "curl-payload.json"
        self.bin_dir = self.workdir / "bin"
        self.bin_dir.mkdir()
        self._write_curl_stub()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_curl_stub(self) -> None:
        curl_path = self.bin_dir / "curl"
        curl_path.write_text(
            "#!/usr/bin/env bash\n"
            "capture_file=\"${LF_CAPTURE_FILE:?}\"\n"
            "data=\"\"\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -d|--data|--data-raw)\n"
            "      shift\n"
            "      data=\"$1\"\n"
            "      ;;\n"
            "  esac\n"
            "  shift || break\n"
            "done\n"
            "printf '%s' \"$data\" > \"$capture_file\"\n"
            "printf '202'\n",
            encoding="utf-8",
        )
        curl_path.chmod(curl_path.stat().st_mode | stat.S_IEXEC)

    def _env(self, *, use_env_file: bool = False) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        env["LF_CAPTURE_FILE"] = str(self.capture_file)
        if not use_env_file:
            env["LANGFUSE_PUBLIC_KEY"] = "pk-test"
            env["LANGFUSE_SECRET_KEY"] = "sk-test"
            env["LANGFUSE_HOST"] = "http://langfuse.test"
        return env

    def _run(self, script: Path, payload: dict, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), *args],
            input=json.dumps(payload),
            capture_output=True,
            cwd=self.workdir,
            env=env,
            text=True,
            check=False,
        )

    def test_post_hook_records_summary_without_raw_payloads(self) -> None:
        pre_payload = {
            "session_id": "11111111-2222-3333-4444-555555555555",
            "tool_name": "Bash",
            "tool_input": {"command": "echo SECRET_TOKEN=abc123", "cwd": "/tmp/demo"},
        }
        post_payload = {
            **pre_payload,
            "tool_response": {
                "stderr": "token=abc123",
                "stdout": "secret body",
            },
        }

        pre_result = self._run(HOOK_SCRIPT, pre_payload, "pre", env=self._env())
        self.assertEqual(pre_result.returncode, 0, pre_result.stderr)

        time.sleep(0.02)

        post_result = self._run(HOOK_SCRIPT, post_payload, "post", env=self._env())
        self.assertEqual(post_result.returncode, 0, post_result.stderr)

        payload = json.loads(self.capture_file.read_text(encoding="utf-8"))
        body = payload["batch"][0]["body"]
        payload_text = json.dumps(payload)

        self.assertNotIn("SECRET_TOKEN=abc123", payload_text)
        self.assertNotIn("secret body", payload_text)
        self.assertNotIn("token=abc123", payload_text)
        self.assertEqual(body["input"]["top_level_keys"], ["command", "cwd"])
        self.assertEqual(body["output"]["top_level_keys"], ["stderr", "stdout"])
        self.assertGreaterEqual(body["metadata"]["duration_ms"], 0)
        self.assertIn("endTime", body)
        self.assertFalse(any((self.workdir / ".claude" / "langfuse").glob("invocation-*.json")))

    def test_stop_hook_loads_dotenv_and_cleans_state(self) -> None:
        env_file = self.workdir / ".env.local"
        env_file.write_text(
            'LANGFUSE_PUBLIC_KEY="pk local value"\n'
            "LANGFUSE_SECRET_KEY='sk local value'\n"
            "LANGFUSE_HOST=http://langfuse.test/path?mode=local value\n",
            encoding="utf-8",
        )

        payload = {
            "session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }

        pre_result = self._run(HOOK_SCRIPT, payload, "pre", env=self._env(use_env_file=True))
        self.assertEqual(pre_result.returncode, 0, pre_result.stderr)

        stop_result = self._run(
            STOP_SCRIPT,
            {"session_id": payload["session_id"]},
            env=self._env(use_env_file=True),
        )
        self.assertEqual(stop_result.returncode, 0, stop_result.stderr)

        stop_payload = json.loads(self.capture_file.read_text(encoding="utf-8"))
        body = stop_payload["batch"][0]["body"]

        self.assertEqual(body["metadata"]["session_id"], payload["session_id"])
        self.assertFalse((self.workdir / ".claude" / "langfuse" / "active-session.json").exists())


if __name__ == "__main__":
    unittest.main()
