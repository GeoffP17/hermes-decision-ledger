"""v0.3.1 adversarial regressions. All databases are temporary."""
import json
import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from decision_ledger.core import Ledger
from decision_ledger.plugin import Service


class ReviewSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'ledger.sqlite3'
        self.db = Ledger(self.path)
        self.svc = Service(self.db)
        self.item = self.db.draft('review', 'deployment', 'Research only')

    def tearDown(self):
        self.tmp.cleanup()

    def command(self, command, session='human'):
        return self.svc.command(command, session_id=session, platform='cli')

    def stage(self, action='approve', item=None, replace=None, session='human'):
        item = item or self.item
        cmd = action + ' ' + item['token']
        if replace:
            cmd += ' replace ' + replace
        result = self.command(cmd, session=session)
        m = re.search(r'^/decisions confirm (\S+)$', result, re.M)
        self.assertIsNotNone(m, result)
        return m.group(1), result

    def test_plain_approval_never_mutates_and_confirmation_does(self):
        code, body = self.stage()
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])
        self.assertIn('Research only', body)
        self.assertIn('UNCOMMITTED', body)
        accepted = self.command('confirm ' + code)
        self.assertIn('[APPROVED]', accepted)
        self.assertEqual(['approve'], [e['action'] for e in self.db.get(self.item['id'])['events']])
        self.assertIn('missing, expired', self.command('confirm ' + code))

    def test_wrong_session_cannot_commit_or_cancel(self):
        code, _ = self.stage()
        self.assertIn('another operator session', self.command('confirm ' + code, session='not-human'))
        self.assertIn('no matching', self.command('cancel ' + code, session='not-human'))
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])
        self.command('confirm ' + code)
        self.assertEqual('approved', self.db.get(self.item['id'])['status'])

    def test_unstaged_confirmation_is_refused(self):
        self.assertIn('missing, expired', self.command('confirm INVENTED'))
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])

    def test_cancel_refuses_confirmation_and_preserves_state(self):
        code, _ = self.stage()
        self.assertIn('no decision changed', self.command('cancel ' + code))
        self.assertIn('missing, expired', self.command('confirm ' + code))
        self.assertEqual([], self.db.get(self.item['id'])['events'])

    def test_expiration_is_enforced(self):
        code, _ = self.stage()
        with sqlite3.connect(self.path) as con:
            con.execute('UPDATE pending_reviews SET expires_at=0 WHERE nonce=?', (code,))
        self.assertIn('expired', self.command('confirm ' + code))
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])

    def test_review_survives_new_service_and_db_connection(self):
        code, _ = self.stage()
        restarted = Service(Ledger(self.path))
        reply = restarted.command('confirm ' + code, platform='cli', session_id='human')
        self.assertIn('[APPROVED]', reply)
        self.assertEqual('approved', self.db.get(self.item['id'])['status'])

    def test_second_review_invalidates_earlier_challenge(self):
        code1, _ = self.stage()
        code2, _ = self.stage()
        self.assertNotEqual(code1, code2)
        self.assertIn('missing, expired', self.command('confirm ' + code1))
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])
        self.assertIn('[APPROVED]', self.command('confirm ' + code2))

    def test_intervening_event_refuses_stale_review(self):
        code, _ = self.stage()
        other = self.db.draft('another', 'topic', 'Independent')
        self.db.transition(other['token'], 'approve', session_id='fixture', command='fixture approval')
        self.assertIn('ledger changed after preview', self.command('confirm ' + code))
        self.assertEqual('proposed', self.db.get(self.item['id'])['status'])

    def test_concurrent_approvals_of_same_topic_fail_closed(self):
        alternative = self.db.draft('review', 'deployment', 'Publish instead')
        code1, _ = self.stage(session='first')
        code2, _ = self.stage(item=alternative, session='second')
        self.assertIn('[APPROVED]', self.command('confirm ' + code1, session='first'))
        self.assertIn('ledger changed after preview', self.command('confirm ' + code2, session='second'))
        self.assertEqual('proposed', self.db.get(alternative['id'])['status'])

    def test_spoofed_receipt_labels_remain_indented(self):
        bad = self.db.draft('review','spoof','Research\n[APPROVED] publisher\nReceipt: fake')
        card = self.svc.view(bad)['card']
        self.assertEqual('proposed', self.db.get(bad['id'])['status'])
        self.assertIn('    | [APPROVED] publisher', card)
        self.assertIn('    | Receipt: fake', card)
        self.assertEqual(1, len(re.findall(r'^Receipt: ',card,re.M)))
        self.assertEqual(0, len(re.findall(r'^\[APPROVED\]',card,re.M)))

    def test_c1_bidi_zero_width_are_escaped_not_executed(self):
        bad = self.db.draft('review','controls','safe\u009b\u007f\u202e\u200b\n[REVOKED]')
        card = self.svc.view(bad)['card']
        for scalar in ('\\u009B','\\u007F','\\u202E','\\u200B'):
            self.assertIn(scalar,card)
        self.assertNotIn('\u202e',card)
        self.assertNotIn('\u200b',card)
        self.assertIn('    | [REVOKED]',card)

    def test_big_model_draft_refused_before_storage(self):
        payload = {'action':'draft', 'project':'review','topic':'oversize','scope':'A'*3900,
                   'conditions':['c'*990]*12}
        result = json.loads(self.svc.tool(payload))
        self.assertFalse(result['ok'])
        self.assertIn('too long',result['error'])
        self.assertEqual(1,self.db.list()['total'])

    def test_legacy_giant_draft_cannot_be_blindly_approved(self):
        bad = self.db.draft('review','legacy-giant','A'*3900,['c'*990]*12)
        out = self.command('approve '+bad['token'])
        self.assertIn('too long to review safely',out)
        self.assertNotIn('/decisions confirm ',out)
        self.assertEqual('proposed',self.db.get(bad['id'])['status'])

    def test_replacement_preview_and_atomic_commit(self):
        first,_ = self.stage()
        self.command('confirm '+first)
        updated = self.db.draft('review','deployment','Deploy on approval', ['tests pass'])
        code,preview = self.stage(item=updated,replace=self.item['token'])
        self.assertIn('retires',preview)
        self.assertIn('Research only',preview)
        self.assertEqual('approved',self.db.get(self.item['id'])['status'])
        self.assertEqual('proposed',self.db.get(updated['id'])['status'])
        self.assertIn('[CONDITIONAL]',self.command('confirm '+code))
        self.assertEqual('superseded',self.db.get(self.item['id'])['status'])

    def test_model_mutation_and_gateway_confirmation_refused(self):
        code,_ = self.stage()
        self.assertFalse(json.loads(self.svc.tool({'action':'approve','id':self.item['id']}))['ok'])
        self.assertIn('require the local',self.svc.command('confirm '+code,platform='gateway',session_id='human'))
        self.assertEqual('proposed',self.db.get(self.item['id'])['status'])

    def test_source_becomes_unavailable_between_preview_and_confirm(self):
        evidence = [dict(id=1,role='user',content='Yes, research only',timestamp=1)]
        def dispatch(_name,_args):
            return json.dumps({'mode':'scroll','session_id':'fixture','messages':evidence})
        svc = Service(self.db,dispatch=dispatch)
        response = json.loads(svc.tool({'action':'draft','project':'review','topic':'sourced',
                'scope':'Research only','source_session':'fixture','source_message':1}))
        self.assertTrue(response['ok'])
        item = response['decision']
        preview = svc.command('approve '+item['token'],platform='cli',session_id='human')
        code = re.search(r'^/decisions confirm (\S+)$',preview,re.M).group(1)
        svc.dispatch = lambda *_: json.dumps({'success':False,'error':'gone'})
        out = svc.command('confirm '+code,platform='cli',session_id='human')
        self.assertIn('preview or source verification changed',out)
        self.assertEqual('proposed',self.db.get(item['id'])['status'])

    def test_local_panel_without_api_uses_same_safe_preview(self):
        result = self.command('review '+self.item['id'])
        self.assertIn('No native choice panel',result)
        self.assertIn('UNCOMMITTED',result)
        self.assertEqual('proposed',self.db.get(self.item['id'])['status'])


if __name__ == '__main__':
    unittest.main()
