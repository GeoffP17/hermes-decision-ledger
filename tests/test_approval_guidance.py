"""Approval discovery and transport refusal must agree without adding authority."""
import json
import tempfile
import unittest
from pathlib import Path
from decision_ledger.core import Ledger
from decision_ledger.plugin import Service, PROMPT, SCHEMA

class ApprovalGuidance(unittest.TestCase):
    def test_model_and_draft_card_point_to_operator(self):
        with tempfile.TemporaryDirectory() as d:
            s = Service(Ledger(Path(d)/'ledger.sqlite3'))
            out = s.tool(dict(action='draft',project='ux',topic='test',scope='Research only'))
            self.assertIn('operator_console.py', out)
            self.assertIn('confirm REVIEW_CODE', out)
            self.assertNotIn('Start LOCAL review (does not approve): /decisions approve', out)
        for text in (PROMPT, SCHEMA['description']):
            self.assertIn('operator_console.py', text)
            self.assertIn('Gateway' if text == SCHEMA['description'] else 'gateway', text)

    def test_gateway_refusal_is_actionable_and_leaves_no_events(self):
        with tempfile.TemporaryDirectory() as d:
            s = Service(Ledger(Path(d)/'ledger.sqlite3'))
            item=s.ledger.draft('ux','test','Research only',[])
            for action in ('approve '+item['token'], 'confirm MADE_UP'):
                out=s.command(action, platform='local', source='gateway',session_id='ux')
                self.assertIn('operator_console.py',out)
                self.assertIn('read-only',out)
            current=s.ledger.get(item['id'])
            self.assertEqual(current['status'],'proposed')
            self.assertEqual(current['events'],[])
