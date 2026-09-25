import unittest
from pathlib import Path
from unittest.mock import patch
from agent_platform_mcp.tools import routing, projects


class RoutingTest(unittest.TestCase):
    def resolve(self, cfg, **kwargs):
        with patch.object(routing,'configuration',return_value=cfg):
            return routing.resolve('backend',projects.ProjectContext('demo',Path('/project')),**kwargs)

    def test_project_and_explicit_choices_preserve_backend_model_pair(self):
        cfg={'preferred_cli':'codex','cli_models':{'codex':'code-default'},'claude_models':{'backend':'opus'},
             'routing':{'roles':{'backend':{'cli':'codex'}},'projects':{'demo':{'backend':{'cli':'claude','models':{'claude':'sonnet'}}}}}}
        self.assertEqual(self.resolve(cfg)['model'],'sonnet')
        selected=self.resolve(cfg,cli='codex')
        self.assertEqual((selected['cli'],selected['model']),('codex','code-default'))
        self.assertEqual(self.resolve(cfg,cli='claude',model='custom')['model'],'custom')

    def test_policy_cannot_be_bypassed_by_explicit_selection(self):
        cfg={'routing':{'allowed_cli':['codex'],'allowed_models':{'codex':['approved']}}}
        for kwargs in ({'cli':'claude'},{'cli':'codex','model':'other'},{'cli':'codex'}):
            with self.assertRaises(ValueError):self.resolve(cfg,**kwargs)
        self.assertEqual(self.resolve(cfg,cli='codex',model='approved')['model'],'approved')

    def test_unknown_and_invalid_policy_rejected(self):
        for cfg in ({'routing':None},{'routing':{'roles':{'backend':{'cli':'typo'}}}},
                    {'routing':{'allowed_cli':'codex'}},{'routing':{'roles':{'unknown':{'cli':'codex'}}}}):
            with self.assertRaises(ValueError):self.resolve(cfg)
        with self.assertRaises(ValueError):self.resolve({},model='--bad')


from test_feature_tools import ActiveProjectTestCase
from test_observation import ObservationFixture


class BackendSelectionIntegrationTest(ActiveProjectTestCase):
    def setUp(self):
        super().setUp()
        self.write_artifact('pay','PRD.md')
        self.write_artifact('pay','TASK.md')

    def test_every_role_forwards_claude_and_model(self):
        from agent_platform_mcp.tools import backend,plan,review,audit,qa,release,investment,quant,investment_risk
        for module in (backend,plan,review,audit,qa,release,investment,quant,investment_risk):
            with self.subTest(module=module.__name__):
                options={'requirements':'fixture'} if module in (plan,investment,quant,investment_risk) else {}
                if module in (investment,quant,investment_risk):options['as_of']='2026-09-25'
                result=module.run('pay',cli='claude',model='model-test',dry_run=True,**options)
                command=result['command']
                self.assertEqual(command[:2],['claude','-p'])
                self.assertEqual(command[command.index('--model')+1],'model-test')
                self.assertNotIn('--dangerously-skip-permissions',command)
                self.assertEqual(result['selection']['cli_source'],'explicit')
                if module in (investment,quant,investment_risk):
                    toolset=command[command.index('--tools')+1].split(',')
                    self.assertFalse(set(toolset)&{'Write','Edit','Bash'})

    def test_claude_failure_json_is_not_success(self):
        import json,subprocess
        from agent_platform_mcp.tools import runner
        output={'type':'result','subtype':'error_max_turns','is_error':True,'result':'incomplete'}
        with patch('shutil.which',return_value='/fake/claude'),patch('agent_platform_mcp.tools.monitored_process.run',
                return_value=subprocess.CompletedProcess([],0,json.dumps(output),'')):
            result=runner.run_cli('claude',['claude','-p','prompt'],self.resolved_target,5)
        self.assertEqual(result.returncode,1)
        self.assertEqual(result.stdout,'incomplete')

    def test_claude_json_success_and_missing_usage(self):
        import json
        from agent_platform_mcp.tools import native_output
        payload={'type':'result','subtype':'success','is_error':False,'result':'done',
                 'usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':0}}
        body,usage,failed=native_output.claude(json.dumps(payload))
        self.assertEqual(body,'done');self.assertFalse(failed)
        self.assertEqual(usage.input_tokens,100);self.assertIsNone(usage.cache_write_tokens)
        self.assertTrue(native_output.claude('invalid json')[2])


class SelectionObservationTest(ObservationFixture,unittest.TestCase):
    def test_selection_persisted_without_claiming_runtime_model(self):
        from agent_platform_mcp.tools import runner,store
        cfg={'routing':{'roles':{'backend':{'cli':'claude','models':{'claude':'test-model'}}}}}
        with patch.object(routing,'configuration',return_value=cfg):
            result=runner.execute(projects.resolve('test-project'),'sample-task','backend','auto',None,False,
                                  lambda cli,model:{'exit_code':0})
        self.assertTrue(result['observability']['stored'])
        with store.open() as db:record=db.run(result['run_id'])
        self.assertEqual(record['model'],'test-model')
        self.assertEqual(record['payload']['selection']['runtime_model_status'],'unverified')
        self.assertEqual(record['payload']['selection']['cli_source'],'role')

    def test_selection_metadata_rejects_raw_content(self):
        from dataclasses import replace
        from agent_platform_mcp import events
        from agent_platform_mcp.tools import observation,store
        result=observation.run_start('sample-task','backend',root='test-project')
        with store.open() as db:
            original=db.run(result['run_id'])
            event=events.RunEvent(**{key:original[key] for key in events.RunEvent.__dataclass_fields__})
            with self.assertRaises(ValueError):
                db.record_event(replace(event,payload={**event.payload,'selection':{'prompt':'raw'}}))


class RoutingEntrypointsTest(unittest.TestCase):
    def test_standalone_passes_model_and_explicit_backend(self):
        import io
        from contextlib import redirect_stdout
        from agent_platform_mcp import cli
        with patch.object(cli.backend,'run',return_value={'dry_run':True}) as run,redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['run','backend','sample-task','--ai','claude','--model','sonnet','--dry-run']),0)
        self.assertEqual(run.call_args.kwargs['cli'],'claude')
        self.assertEqual(run.call_args.kwargs['model'],'sonnet')

    def test_malformed_file_never_falls_back(self):
        import tempfile
        from agent_platform_mcp import config
        with tempfile.TemporaryDirectory() as directory,patch.object(config,'ROOT',Path(directory).resolve()):
            (config.ROOT/'.agent-config.json').write_text('{broken')
            with self.assertRaises(ValueError):routing.resolve('backend',projects.ProjectContext(None,config.ROOT))

    def test_disallowed_route_does_not_execute_action(self):
        from agent_platform_mcp.tools import runner
        from unittest.mock import Mock
        action=Mock()
        with patch.object(routing,'configuration',return_value={'routing':{'allowed_cli':['codex']}}):
            with self.assertRaises(ValueError):
                runner.execute(projects.ProjectContext(None,Path('/project')),'sample-task','backend','claude',None,False,action)
        action.assert_not_called()
