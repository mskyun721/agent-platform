import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from test_observation import ObservationFixture
from agent_platform_mcp.tools import learning


class ImprovementsTest(ObservationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        from agent_platform_mcp import config
        self.root_patch=patch.object(config,'ROOT',self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.target=self.root/'standards/reference/lesson.md'
        self.target.parent.mkdir(parents=True)
        self.target.write_text('Original rule\n')
        self.feedback=learning.add('test-project','manual',None,'correction','Check current sessions')

    def module(self):
        from agent_platform_mcp.tools import improvements
        return improvements

    def propose(self):
        return self.module().propose('test-project',self.feedback['id'],trigger='reporting health',action='check active session',target='standards/reference/lesson.md',replacement='Check active session\n')

    def records(self,candidate):
        folder=self.root/'evals/results'
        folder.mkdir(parents=True,exist_ok=True)
        groups=[[],[]]
        for group,variant in enumerate(('baseline','candidate')):
            for backend in ('claude','codex'):
                for i in range(3):
                    identity=str(uuid4())
                    row={'run_id':identity,'status':'checked','passed':True,'task':'scope','task_hash':'a'*64,'model':backend+'-test',
                         'cli_version':'1.0.0','ai':backend,'instruction_mode':'platform','python':'test-python',
                         'platform_fingerprint':'b'*64,'evaluation_budget_sec':60,'verification_exit_code':0,'human_interventions':0,
                         'improvement_id':candidate['id'],'improvement_hash':candidate['content_hash'],
                         'improvement_variant':variant,'instruction_content_hash':candidate['target_hash'] if group==0 else candidate['replacement_hash']}
                    (folder/(identity+'.json')).write_text(json.dumps(row))
                    groups[group].append(identity)
        return groups

    def evaluated(self):
        item=self.propose()
        baseline,candidate=self.records(item)
        self.module().evaluate('test-project',item['id'],baseline,candidate)
        return item,baseline,candidate

    def test_missing_approval_and_stale_target_blocked(self):
        m=self.module();item=self.propose()
        with self.assertRaises(ValueError):m.apply('test-project',item['id'])
        with self.assertRaises(ValueError):m.review('test-project',item['id'],'approved','operator')
        self.target.write_text('User changed\n')
        self.assertEqual(m.show('test-project',item['id'])['status'],'stale')
        self.assertEqual(self.target.read_text(),'User changed\n')

    def test_evaluate_review_apply_revert_and_user_edits(self):
        m=self.module();item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        dry=m.apply('test-project',item['id'],dry_run=True)
        self.assertIn('Check active session',dry['diff'])
        self.assertEqual(self.target.read_text(),'Original rule\n')
        m.apply('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'Check active session\n')
        self.target.write_text('User followup\n')
        with self.assertRaises(ValueError):m.revert('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'User followup\n')
        self.target.write_text('Check active session\n')
        reverse = m.revert('test-project',item['id'],dry_run=True)
        self.assertIn('-Check active session', reverse['diff'])
        self.assertIn('+Original rule', reverse['diff'])
        m.revert('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'Original rule\n')

    def test_modified_eval_and_purged_feedback_block_apply(self):
        m=self.module();item,_,runs=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        path=self.root/'evals/results'/f'{runs[0]}.json'
        row=json.loads(path.read_text());row['passed']=False;path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):m.apply('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'Original rule\n')
        learning.purge('test-project')
        with self.assertRaises(ValueError):m.evaluate('test-project',item['id'],[],[])

    def test_invalid_target_and_missing_feedback_rejected(self):
        m=self.module()
        for target in ('../outside.md','README.md','standards/reference/../reference/lesson.md'):
            with self.assertRaises(ValueError):
                m.propose('test-project',self.feedback['id'],trigger='x',action='y',target=target,replacement='x')
        with self.assertRaises(ValueError):
            m.propose('test-project',str(uuid4()),trigger='x',action='y',target='standards/reference/lesson.md',replacement='x')

    def test_bad_results_do_not_promote(self):
        m=self.module();item=self.propose();baseline,candidate=self.records(item)
        path=self.root/'evals/results'/f'{candidate[0]}.json'
        row=json.loads(path.read_text());row['status']='prepared';path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):m.evaluate('test-project',item['id'],baseline,candidate)
        self.assertEqual(m.show('test-project',item['id'])['status'],'draft')

    def test_interrupted_apply_can_resume_or_revert(self):
        m=self.module();item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        original_save=m._save
        def fail_final(value):
            if value['status']=='applied':raise OSError('simulated crash after file replacement')
            return original_save(value)
        with patch.object(m,'_save',side_effect=fail_final):
            with self.assertRaises(OSError):m.apply('test-project',item['id'])
        self.assertEqual(m.show('test-project',item['id'])['status'],'applying')
        m.revert('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'Original rule\n')

    def test_agent_adapter_is_applied_and_reverted_together(self):
        m=self.module()
        target=self.root/'standards/agents/backend.md';target.parent.mkdir(parents=True);target.write_text('Original role\n')
        adapter=self.root/'.claude/agents/backend.md';adapter.parent.mkdir(parents=True)
        old='---\nname: backend\nmodel: test\n---\n<!-- generated from standards/agents/backend.md; edit the source, then run scripts/sync_claude_settings.py --agents-only -->\nOriginal role\n'
        adapter.write_text(old)
        item=m.propose('test-project',self.feedback['id'],trigger='x',action='y',target='standards/agents/backend.md',replacement='Updated role\n')
        baseline,candidate=self.records(item);m.evaluate('test-project',item['id'],baseline,candidate)
        m.review('test-project',item['id'],'approved','operator');m.apply('test-project',item['id'])
        self.assertIn('Updated role',adapter.read_text())
        m.revert('test-project',item['id']);self.assertEqual(adapter.read_text(),old)

    def test_comparison_rejects_mismatch_and_insufficient_trials(self):
        m=self.module();item=self.propose();baseline,candidate=self.records(item)
        with self.assertRaises(ValueError):m.evaluate('test-project',item['id'],baseline[:1],candidate[:1])
        path=self.root/'evals/results'/f'{candidate[0]}.json';row=json.loads(path.read_text())
        row['task_hash']='different';path.write_text(json.dumps(row))
        with self.assertRaises(ValueError):m.evaluate('test-project',item['id'],baseline,candidate)

    def test_invalid_reevaluation_revokes_prior_approval(self):
        m=self.module();item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        with self.assertRaises(ValueError):m.evaluate('test-project',item['id'],[],[])
        current=m.show('test-project',item['id'])
        self.assertEqual(current['status'],'draft')
        self.assertIsNone(current['review'])
        with self.assertRaises(ValueError):m.apply('test-project',item['id'])

    def test_expiry_blocks_unapplied_but_preserves_rollback(self):
        m=self.module();item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        with patch.object(m.time,'time',return_value=time.time()+learning.RETENTION+1):
            self.assertEqual(m.show('test-project',item['id'])['status'],'stale')
            with self.assertRaises(ValueError):m.apply('test-project',item['id'])
        self.feedback=learning.add('test-project','manual',None,'correction','Check current sessions')
        item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        m.apply('test-project',item['id'])
        learning.purge('test-project')
        with patch.object(m.time,'time',return_value=time.time()+learning.RETENTION+1):
            m.revert('test-project',item['id'])
        self.assertEqual(self.target.read_text(),'Original rule\n')

    def test_external_root_and_symlink_cannot_be_applied(self):
        from agent_platform_mcp import config
        m=self.module();item,_,_=self.evaluated()
        m.review('test-project',item['id'],'approved','operator')
        with patch.object(config,'ROOT',self.root/'different-checkout'):
            with self.assertRaises(ValueError):m.apply('test-project',item['id'])
        self.target.unlink()
        self.target.symlink_to(self.root/'outside.md')
        (self.root/'outside.md').write_text('Original rule\n')
        with self.assertRaises(ValueError):m.apply('test-project',item['id'])
        self.assertEqual((self.root/'outside.md').read_text(),'Original rule\n')

    def test_cli_proposal_show_and_root_requirement(self):
        import contextlib
        import io
        from agent_platform_mcp.cli import main
        payload={'trigger':'health check','action':'check session','target':'standards/reference/lesson.md',
                 'replacement':'Check current session\n'}
        output=io.StringIO()
        with patch('sys.stdin',io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
            self.assertEqual(main(['improvement','propose','--root','test-project','--feedback',self.feedback['id']]),0)
        item=json.loads(output.getvalue())
        self.assertEqual(item['status'],'draft')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['improvement','show',item['id'],'--root','test-project']),0)
        self.assertIn('+Check current session',json.loads(output.getvalue())['diff'])
        with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as raised:
            main(['improvement','list'])
        self.assertEqual(raised.exception.code,2)
