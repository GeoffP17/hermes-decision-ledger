import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from decision_ledger.core import Ledger, LedgerError
from decision_ledger.reader import ReceiptReader
from test_ledger import Fixture

class ReaderTests(unittest.TestCase):
    def test_missing_database_does_not_create_storage(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'missing'/'ledger.sqlite3'
            self.assertEqual(ReceiptReader(p).page()['total'],0)
            self.assertFalse(p.parent.exists())

    def test_receipt_matches_core_without_writes_or_private_metadata(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'ledger.sqlite3';ledger=Ledger(p)
            item=ledger.draft('website','hosting','Research only', ['No spending'])
            before=p.read_bytes();reader=ReceiptReader(p);page=reader.page()
            self.assertEqual(p.read_bytes(),before)
            record=page['decisions'][0]
            self.assertEqual(record['scope'],item['scope'])
            self.assertEqual(record['status'],'proposed')
            self.assertNotIn('evidence',record)
            self.assertNotIn('pending_reviews',json.dumps(page))
            with self.assertRaises(LedgerError):
                with reader.connect(write=True): pass
            with reader.connect() as db:
                with self.assertRaises(sqlite3.OperationalError):db.execute('DELETE FROM proposals')

    def test_pagination_and_tamper_refusal(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'ledger.sqlite3';ledger=Ledger(p)
            for i in range(3):ledger.draft('website',str(i),'Research only')
            reader=ReceiptReader(p)
            self.assertEqual(reader.page(limit=2)['next_offset'],2)
            self.assertEqual(len(reader.page(offset=2,limit=2)['decisions']),1)
            with self.assertRaises(LedgerError):reader.page(limit=101)
            with sqlite3.connect(p) as db:
                db.execute("UPDATE proposals SET payload='{}'")
            with self.assertRaises((LedgerError,KeyError)):reader.page()

class ReaderLifecycleTests(Fixture, unittest.TestCase):
    def test_confirmed_and_revoked_status_follow_core(self):
        item=self.approve(self.draft())
        reader=ReceiptReader(self.path)
        self.assertEqual(reader.page()['decisions'][0]['status'],'approved')
        self.command('revoke',item)
        record=reader.page()['decisions'][0]
        self.assertEqual(record['status'],'revoked')
        self.assertEqual([e['action'] for e in record['events']],['approve','revoke'])
        self.assertTrue(all(set(e)=={'action','created_at'} for e in record['events']))
