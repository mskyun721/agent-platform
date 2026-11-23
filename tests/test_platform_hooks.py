import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/hooks/platform_hook.py'


class PlatformHookTest(unittest.TestCase):
    def invoke(self, payload):
        result = subprocess.run([sys.executable,str(SCRIPT)],input=payload,text=True,capture_output=True,cwd=tempfile.gettempdir())
        self.assertEqual(result.returncode,0)
        return json.loads(result.stdout)

    def test_dangerous_command_denied_without_execution(self):
        r=self.invoke(json.dumps({'hook_event_name':'PreToolUse','tool_input':{'command':'sudo rm /important'}}))
        self.assertEqual(r['hookSpecificOutput']['permissionDecision'],'deny')

    def decision(self, tool, tool_input):
        r = self.invoke(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': tool, 'tool_input': tool_input}))
        return r.get('hookSpecificOutput', {}).get('permissionDecision')

    def test_boundary_commands_and_registry_writes_ask_the_user(self):  # SECURITY F1, N-6, H-UX
        for command in ('uv --directory mcp-server run agent-platform-agent project-workspace add ~',
                        'agent-platform-agent project-workspace remove ~/old --allow-empty',
                        'agent-platform-agent project-add /tmp/x --default', 'agent-platform-agent project-migrate',
                        'agent-platform-agent project-use svc', 'agent-platform-agent project-register / ',
                        'agent-platform-agent project-rebind svc /tmp', './scripts/setup.sh --roots ~',
                        'agent-platform-agent project-publish-set svc --target none',  # N-6
                        'agent-platform-agent project-spec-set svc x',  # any future project-*-set
                        'agent-platform-agent project-a-b-set svc',
                        'echo {} > .agent-projects.json', 'echo x >> /repo/.agent-projects.json',
                        'cat new.json | tee .agent-projects.json', 'cp /backup/x.json .agent-projects.json',
                        'mv tmp.json /repo/.agent-projects.json', 'install -m 600 a .agent-projects.json',
                        'ln -sf /elsewhere .agent-projects.json', 'rm -f .agent-projects.lock',
                        'truncate -s 0 .agent-projects.json', "sed -i '' s/a/b/ .agent-projects.json",
                        'perl -pi -e s/a/b/ .agent-projects.json',
                        'python3 -c "open(\'.agent-projects.json\',\'w\').write(\'{}\')"',
                        "python3 - <<'EOF'\nfrom pathlib import Path\nPath('.agent-projects.json').write_text('{}')\nEOF",
                        'python3 -c "open(\'/r/.agent-projects.json\', \'a\')"',
                        'python3 -c "open(\'.agent-projects.json\', mode=\'x\')"',
                        # SECURITY F8: deletes and swaps of the registry (env fallback would return)
                        'mv .agent-projects.json .agent-projects.json.bak', 'mv -f .agent-projects.json /tmp/',
                        'python3 -c "import os; os.remove(\'.agent-projects.json\')"',
                        'python3 -c "import os; os.replace(\'/tmp/x\', \'.agent-projects.json\')"',
                        'python3 -c "import os; os.rename(\'.agent-projects.json\', \'old\')"',
                        'python3 -c "import shutil; shutil.copy(\'/tmp/x\', \'.agent-projects.json\')"',
                        'python3 -c "open(\'.agent-projects.json\', \'r+\').truncate()"',
                        'python3 -c "from pathlib import Path; Path(\'.agent-projects.json\').unlink()"',
                        'node -e "require(\'fs\').writeFileSync(\'.agent-projects.json\', \'{}\')"',
                        'dd if=/tmp/x of=.agent-projects.json', 'rsync -a /tmp/x .agent-projects.json',
                        'find . -maxdepth 1 -name .agent-projects.json -delete',
                        'rm .active-project.migrated',  # the migration marker keeps the env fallback off
                        # SECURITY F9 / REVIEW L-9: case variants reach the same file on macOS
                        'cp /tmp/x .Agent-Projects.json', 'echo {} > .AGENT-PROJECTS.JSON',
                        # SECURITY F11: a `--dry-run` inside a comment is not a dry run
                        'agent-platform-agent project-migrate  # --dry-run',
                        # REVIEW L-8: real invocations in every form, project-unregister included
                        'uv run agent-platform-agent project-unregister old', 'apa project-use svc',
                        'python3 -m agent_platform_mcp.cli project-add /x',
                        'bash -c "agent-platform-agent project-use svc"', 'eval agent-platform-agent project-use svc',
                        'cd mcp-server && uv run agent-platform-agent project-migrate',
                        'bash scripts/setup.sh --target /x', './scripts/setup.sh --roots=/x'):
            with self.subTest(command=command):
                self.assertEqual(self.decision('Bash', {'command': command}), 'ask')
        for path in ('/repo/.agent-projects.json', '.agent-projects.lock', '/repo/.AGENT-PROJECTS.JSON',
                     '/repo/.active-project.migrated', '/repo/.claude/settings.local.json', '.claude/Settings.json'):
            for tool in ('Write', 'Edit', 'MultiEdit'):
                with self.subTest(tool=tool, path=path):
                    self.assertEqual(self.decision(tool, {'file_path': path}), 'ask')

    def test_reads_previews_and_other_edits_pass(self):  # H-UX: no prompt for read-only forms
        backup = '/private/tmp/x/rework-agent-projects.json.bak'
        for command in ('agent-platform-agent project-list', 'agent-platform-agent project-publish-show svc',
                        'agent-platform-agent project-workspace list', 'agent-platform-agent project-migrate --dry-run',
                        'uv --directory ./mcp-server run agent-platform-agent project-migrate --dry-run',
                        'uv --directory ./mcp-server run agent-platform-agent doctor --root .',
                        'agent-platform-agent gate-check refactor/x', 'git status',
                        # REVIEW L-8: mentions of a CLI name are reads, not invocations
                        "grep -n 'project-use' README.md", 'rg -n "project-migrate" standards/',
                        'git log --grep project-add', 'git diff HEAD | grep "project-workspace add"',
                        'git commit -m "docs: project-add 와 project-unregister 설명"', 'man agent-platform-agent',
                        'grep -rn "agent-platform-agent project-use" README.md', 'grep -n "setup.sh --roots" README.md',
                        'cat standards/reference/setup.md', 'agent-platform-agent project-list  # then project-use',
                        'uv --directory ./mcp-server run --locked --dev python -m pytest -q ../tests',
                        f'cp .agent-projects.json /backup', f'cp -p .agent-projects.json {backup}',
                        f'cmp .agent-projects.json {backup} && echo same', 'cat .agent-projects.json',
                        'grep default .agent-projects.json', 'head -5 .agent-projects.json',
                        'sha256sum .agent-projects.json', 'shasum -a 256 .active-project .agent-projects.json',
                        'cat .agent-projects.json > /tmp/copy.json',
                        'python3 -c "import json; print(json.load(open(\'.agent-projects.json\')))"',
                        'ls -la .agent-projects* 2>&1', 'echo hi > out.txt'):
            with self.subTest(command=command):
                self.assertIsNone(self.decision('Bash', {'command': command}))
        for path in ('/repo/README.md', '/repo/.env.example', '/repo/docs/settings.json'):
            self.assertIsNone(self.decision('Edit', {'file_path': path}))
        self.assertEqual(self.decision('Write', {'content': 'x'}), 'deny')  # malformed edit input

    def test_copilot_edit_input_uses_path_key(self):
        # Copilot CLI runs the same hook; its edit/create tools name the target `path`.
        self.assertIsNone(self.decision('Edit', {'path': '/repo/README.md', 'old_str': 'a', 'new_str': 'b'}))
        self.assertIsNone(self.decision('Write', {'path': '/repo/docs/WORK.md', 'file_text': 'x'}))
        for path in ('/repo/.agent-projects.json', '/repo/.claude/settings.local.json'):
            self.assertEqual(self.decision('Edit', {'path': path, 'old_str': 'a', 'new_str': 'b'}), 'ask')
        # every path key present is inspected, so a harmless one cannot hide a guarded one
        self.assertEqual(self.decision('Edit', {'file_path': '/repo/README.md', 'path': '/repo/.agent-projects.json'}), 'ask')
        self.assertEqual(self.decision('Edit', {'file_path': '/repo/README.md', 'path': 7}), 'deny')
        self.assertEqual(self.decision('Edit', {'path': ''}), 'deny')

    def test_guard_is_registered_for_edits_too(self):
        settings = json.loads((SCRIPT.parents[2] / '.claude/settings.json').read_text(encoding='utf-8'))
        matchers = [entry['matcher'] for entry in settings['hooks']['PreToolUse']
                    if any('platform_hook.py' in hook['command'] for hook in entry['hooks'])]
        self.assertEqual(len(matchers), 3)
        self.assertTrue({'Bash', 'Write', 'Edit', 'MultiEdit'} <= set(matchers[0].split('|')))
        self.assertEqual(matchers[1], 'mcp__agent-platform__observe_capture')  # SECURITY M1: MCP names are matchable
        self.assertEqual(matchers[2], 'mcp__agent-platform__publish_spec')  # Security 4b RA-L3

    def test_publish_spec_confirm_or_allow_draft_asks_and_a_plan_passes(self):  # Security 4b RA-L3, Review RL-4
        tool = 'mcp__agent-platform__publish_spec'
        for arguments in ({'slug': 'pay', 'confirm': True}, {'index': True, 'confirm': True},
                          {'slug': 'pay', 'confirm': 'true'}, {'slug': 'pay', 'confirm': 1},
                          {'slug': 'pay', 'allow_draft': True}, {'slug': 'pay', 'allow_draft': True, 'dry_run': True},
                          {'slug': 'pay', 'allow_draft': True, 'confirm': False}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self.decision(tool, arguments), 'ask')
        for arguments in ({'slug': 'pay'}, {'slug': 'pay', 'dry_run': True}, {'index': True, 'confirm': False},
                          {'slug': 'pay', 'confirm': False, 'allow_draft': False}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(self.decision(tool, arguments))
        self.assertEqual(self.decision(tool, 'not-a-dict'), 'ask')  # unreadable input never passes silently

    def test_capture_on_asks_and_off_or_preview_pass(self):  # SECURITY M1
        tool = 'mcp__agent-platform__observe_capture'
        self.assertEqual(self.decision(tool, {'root': 'p', 'mode': 'on', 'confirm': True}), 'ask')
        self.assertEqual(self.decision(tool, {'root': 'p', 'mode': 'on', 'confirm': 'true'}), 'ask')
        for arguments in ({'root': 'p', 'mode': 'on'}, {'root': 'p', 'mode': 'on', 'confirm': False}, {'root': 'p', 'mode': 'off'}):
            with self.subTest(arguments=arguments):
                self.assertIsNone(self.decision(tool, arguments))
        self.assertEqual(self.decision('Bash', {'command': 'uv run agent-platform-agent observe capture on --root p'}), 'ask')
        for command in ('agent-platform-agent observe capture off --root p', 'grep "observe capture on" README.md'):
            with self.subTest(command=command):
                self.assertIsNone(self.decision('Bash', {'command': command}))

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

    def test_context_hint_only_on_initial_start(self):
        import importlib.util
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('platform_hook_test',SCRIPT)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        from pathlib import Path as P
        with tempfile.TemporaryDirectory() as tmp, patch.object(module,'ROOT',P(tmp)), \
                patch.object(module.subprocess,'run',return_value=subprocess.CompletedProcess([],0)) as run:
            fresh=module.handle({'hook_event_name':'SessionStart','source':'startup'})
            self.assertIn('scripts/setup.sh',fresh['hookSpecificOutput']['additionalContext'])  # fresh clone
            (P(tmp)/'.env').touch()
            (P(tmp)/'.claude/skills/graphify').mkdir(parents=True)
            self.assertIn('scripts/setup.sh',module.handle({'hook_event_name':'SessionStart','source':'startup'})['hookSpecificOutput']['additionalContext'])
            (P(tmp)/'.claude/skills/ponytail').mkdir()
            run.reset_mock()
            message=module.handle({'hook_event_name':'SessionStart','source':'startup'})
            self.assertIn('observe efficiency',message['hookSpecificOutput']['additionalContext'])
            self.assertLess(len(json.dumps(message)),700)
            self.assertEqual(module.handle({'hook_event_name':'SessionStart','source':'resume'}),{})
            self.assertEqual(module.handle({'hook_event_name':'SessionStart','source':'compact'}),{})
            self.assertEqual(run.call_count,3)  # Existing adapter sync only; no extra CLI/LLM calls.
