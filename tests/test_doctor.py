import time
import unittest
from unittest.mock import patch
from test_observation import ObservationFixture


class DoctorTest(ObservationFixture, unittest.TestCase):
    def test_missing_and_stale_collection_not_healthy(self):
        from agent_platform_mcp.tools import doctor, llm_view
        from agent_platform_mcp import config
        with patch.object(config, 'ROOT', self.root):
            result = doctor.observation_status('test-project')
            self.assertEqual(result['collector']['status'], 'unknown')
            with llm_view.content_db() as db:
                db.execute('INSERT INTO collector_health VALUES (?,?)', ('native', '{"checked_at":1,"enabled":true}'))
            self.assertEqual(doctor.observation_status('test-project')['collector']['status'],'stale')

    def test_configured_hook_is_not_execution_evidence(self):
        import json
        from agent_platform_mcp.tools import doctor
        directory = self.root / '.claude'
        directory.mkdir()
        (directory/'settings.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'command':'never execute this'}]}]}}))
        with patch.object(doctor.subprocess, 'run', side_effect=AssertionError('must not run configured hooks')):
            result = doctor.hooks(self.root)
        self.assertEqual(result['claude']['status'], 'configured')
        self.assertEqual(result['claude']['runtime_status'], 'unknown')
