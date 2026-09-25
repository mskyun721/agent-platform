import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hooks/platform_hook.py'


class PlatformHookTest(unittest.TestCase):
    def invoke(self, payload):
        result = subprocess.run([sys.executable,str(SCRIPT)],input=payload,text=True,capture_output=True,cwd='/private/tmp')
        self.assertEqual(result.returncode,0)
        return json.loads(result.stdout)

    def test_dangerous_command_denied_without_execution(self):
        r=self.invoke(json.dumps({'hook_event_name':'PreToolUse','tool_input':{'command':'sudo rm /important'}}))
        self.assertEqual(r['hookSpecificOutput']['permissionDecision'],'deny')

    def test_malformed_pretool_input_does_not_disable_guard(self):
        r=self.invoke('{broken')
        self.assertEqual(r['hookSpecificOutput']['permissionDecision'],'deny')

    def test_secret_warning_does_not_echo_value(self):
        r=self.invoke(json.dumps({'hook_event_name':'UserPromptSubmit','prompt':'API_KEY=do-not-echo-me'}))
        self.assertNotIn('do-not-echo-me',json.dumps(r))
        self.assertIn('additionalContext',r['hookSpecificOutput'])

    def test_benign_command_and_unknown_event(self):
        self.assertEqual(self.invoke(json.dumps({'hook_event_name':'PreToolUse','tool_input':{'command':'git status'}})),{})
        self.assertEqual(self.invoke(json.dumps({'hook_event_name':'Unknown'})),{})
