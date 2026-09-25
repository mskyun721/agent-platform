import unittest
from agent_platform_mcp.tools import usage_efficiency


class UsageEfficiencyTest(unittest.TestCase):
    def row(self, identity, source='native_session', **overrides):
        return {'run_id':identity,'workspace':'/project','backend':'codex','model':'test',
                'collection_source':source,'outcome':'completed','duration_sec':2,
                'usage':{'input_tokens':100,'output_tokens':10,'cache_read_tokens':30,'cache_write_tokens':None},
                'content':{'prompt':'PRIVATE'},'events':['PRIVATE'],**overrides}

    def test_sources_missing_counts_and_failures_remain_distinct(self):
        rows=[self.row('a'),self.row('b',usage=None,outcome='interrupted'),self.row('c','wrapper')]
        result=usage_efficiency.summarize(rows,total=10,limit=3)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['groups']),2)
        native=next(g for g in result['groups'] if g['collection_source']=='native_session')
        self.assertEqual(native['tokens']['input_tokens'],{'known_sum':100,'missing_records':1})
        self.assertEqual(native['tokens']['cache_write_tokens'],{'known_sum':None,'missing_records':2})
        self.assertEqual(native['failed_or_interrupted'],1)
        self.assertNotIn('PRIVATE',str(result))
        self.assertIsNone(result['savings_percent'])

    def test_workspace_filter_and_top_inputs_are_scoped(self):
        result=usage_efficiency.summarize([self.row('a'),self.row('b',workspace='/other',usage={'input_tokens':999})],total=2,limit=5,workspace='/project')
        self.assertEqual(result['sample_records'],1)
        self.assertEqual(result['top_input_runs'][0]['run_id'],'a')
        self.assertEqual(len(result['top_input_runs']),1)
        self.assertFalse(result['truncated'])

    def test_zero_and_unknown_usage_are_not_conflated(self):
        result=usage_efficiency.summarize([self.row('a',usage={'input_tokens':0}),self.row('b',usage={'input_tokens':-1})],total=2,limit=5)
        value=result['groups'][0]['tokens']['input_tokens']
        self.assertEqual(value,{'known_sum':0,'missing_records':1})

    def test_report_resolves_explicit_root_and_filters_existing_sample(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from pathlib import Path
        rows=[self.row('a'),self.row('b',workspace='/other')]
        with patch('agent_platform_mcp.tools.learning.context',return_value=SimpleNamespace(path=Path('/project'))) as context, patch(
            'agent_platform_mcp.tools.llm_view.list_runs',return_value={'runs':rows,'total':2,'limit':500}) as listing:
            report=usage_efficiency.report('registered-project')
        context.assert_called_once_with('registered-project')
        listing.assert_called_once_with(500)
        self.assertEqual(report['sample_records'],1)

    def test_cli_dispatch_and_required_root(self):
        import contextlib
        import io
        from unittest.mock import patch
        from agent_platform_mcp.cli import main
        with patch.object(usage_efficiency,'report',return_value={'sample_records':0}) as report, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['observe','efficiency','--root','project']),0)
        report.assert_called_once_with('project')
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(['observe','efficiency'])
        self.assertEqual(raised.exception.code,2)

    def test_top_inputs_are_ranked_within_each_source_and_model_group(self):
        rows=[self.row(str(i),usage={'input_tokens':1000+i}) for i in range(8)]
        rows.append(self.row('claude',backend='claude',usage={'input_tokens':1}))
        result=usage_efficiency.summarize(rows,total=9,limit=10)
        self.assertEqual(len(result['top_input_runs']),6)
        self.assertIn('claude',[r['run_id'] for r in result['top_input_runs']])
