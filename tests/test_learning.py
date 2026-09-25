import json
import os
import time
import unittest
from unittest.mock import patch
from test_observation import ObservationFixture
from agent_platform_mcp.tools import store, state_queries


class LearningTest(ObservationFixture, unittest.TestCase):
    def module(self):
        from agent_platform_mcp.tools import learning
        return learning

    def test_manual_idempotency_metadata_and_ttl(self):
        m = self.module()
        a = m.add('test-project', 'manual', None, 'correction', 'private-feedback-marker')
        b = m.add('test-project', 'manual', None, 'correction', 'private-feedback-marker')
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(m.show('test-project', a['id'])['summary'], 'private-feedback-marker')
        with store.open() as db:
            self.assertNotIn('private-feedback-marker', '\n'.join(db.connection.iterdump()))
        self.assertEqual(os.stat(self.root / 'learning.db').st_mode & 0o777, 0o600)
        with patch.object(m.time, 'time', return_value=time.time() + 31 * 86400):
            self.assertEqual(m.show('test-project', a['id'])['content_status'], 'missing')

    def test_sources_are_scoped_and_purge_is_scoped(self):
        from agent_platform_mcp.tools import projects, llm_view
        from uuid import uuid4
        m = self.module()
        other = self.root / 'other'
        other.mkdir()
        projects.register(str(other), 'other-project')
        identity = str(uuid4())
        with llm_view.content_db() as db:
            db.execute('INSERT INTO native_runs VALUES (?,?,?,?)', (identity, time.time()+1000, str(self.root), json.dumps({'run_id':identity,'backend':'claude','workspace':str(self.root)})))
        a = m.add('test-project', 'native_turn', identity, 'failure', 'selected issue')
        self.assertEqual(a['backend'], 'claude')
        with self.assertRaises(ValueError):
            m.add('other-project', 'native_turn', identity, 'failure', 'bad scope')
        with self.assertRaises(ValueError):
            m.show('other-project', a['id'])
        other_record = m.add('other-project','manual',None,'suggestion','preserved')
        m.purge('test-project')
        self.assertEqual(m.list_feedback('test-project')['feedback'], [])
        self.assertEqual(m.show('other-project', other_record['id'])['summary'], 'preserved')

    def test_unknown_source_and_invalid_inputs_rejected(self):
        from uuid import uuid4
        m = self.module()
        with self.assertRaises(ValueError):
            m.add('test-project','native_turn',str(uuid4()),'failure','unknown')
        for summary in ('', 'x'*2001, None):
            with self.assertRaises(ValueError):
                m.add('test-project','manual',None,'correction',summary)
        with self.assertRaises(ValueError):
            m.add(None,'manual',None,'correction','missing root')

    def test_platform_source_and_export_excludes_summary(self):
        from agent_platform_mcp.tools import observation, projects
        m = self.module()
        run = observation.start_context('sample-task', 'backend', 'codex', projects.resolve('test-project'))
        # start_context returns the observation API result, not a native content row.
        identity = run['run_id']
        record = m.add('test-project','platform_run',identity,'correction','export-private-marker')
        self.assertEqual(record['backend'],'codex')
        self.assertNotIn('export-private-marker',json.dumps(state_queries.export_snapshot()))

    def test_symlink_content_store_rejected(self):
        target = self.root / 'unrelated.db'
        target.write_text('preserve')
        (self.root/'learning.db').symlink_to(target)
        with self.assertRaises(ValueError):
            self.module().add('test-project','manual',None,'correction','no symlink')
        self.assertEqual(target.read_text(),'preserve')
