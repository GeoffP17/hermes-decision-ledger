"""Smoke-test the shipped local operator through a real POSIX foreground PTY.

All paths/data are disposable. This test neither uses Hermes production nor the network.
"""
import os
from pathlib import Path
import select
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest

PLUGIN = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'real terminal operator requires POSIX')
class TestForegroundOperator(unittest.TestCase):
    def test_local_operator_requires_preview_and_exact_confirmation(self):
        import pty
        with tempfile.TemporaryDirectory(prefix='decision-ledger-local-pty-') as temp:
            home = Path(temp)
            installed = home / 'plugins' / 'decision-ledger'
            shutil.copytree(PLUGIN, installed, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            data_file = home / 'plugin-data' / 'decision-ledger' / 'ledger.sqlite3'
            data_file.parent.mkdir(parents=True)
            sys.path.insert(0, str(installed))
            try:
                from decision_ledger.core import Ledger
                item = Ledger(data_file).draft('demo031', 'deployment',
                    'Research ONLY; no implementation or publication', [])
            finally:
                sys.path.remove(str(installed))
                for name in ('decision_ledger.core', 'decision_ledger', 'decision_ledger.plugin'):
                    sys.modules.pop(name, None)
            pid, fd = pty.fork()
            if pid == 0:
                os.execl(sys.executable, sys.executable, '-u', str(installed/'operator_console.py'))
            data = b''
            def read_until(needle, timeout=8):
                nonlocal data
                limit = time.monotonic() + timeout
                term = needle.encode() if isinstance(needle, str) else needle
                while not (data.endswith(term) if term == b'operator> ' else term in data):
                    if time.monotonic() >= limit:
                        raise AssertionError('operator did not print '+repr(needle)+': '+repr(data[-700:]))
                    ready,_,_ = select.select([fd], [], [], 0.15)
                    if ready:
                        chunk = os.read(fd, 16384)
                        if not chunk: break
                        data += chunk
                self.assertIn(term, data)
                out = data
                data = b''
                return out.decode(errors='replace')
            def send(command): os.write(fd,(command+'\n').encode())
            try:
                read_until('operator> ')
                send('list demo031 deployment')
                read_until('operator> ')
                # Regression: pasted help/transcript fragments must not flood multi-page HELP
                # or accidentally create receipt events; give a short actionable refusal.
                send('accidentally_pasted_transcript')
                pasted = read_until('operator> ')
                self.assertIn('Enter ONE command line only', pasted)
                self.assertNotIn('Commands (at operator> prompt):', pasted)
                with sqlite3.connect(data_file) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                send('approve '+item['token'])
                message = read_until('operator> ')
                self.assertIn('NO RECEIPT STATE HAS CHANGED', message)
                code = message.split('  confirm ',1)[1].splitlines()[0].strip()
                self.assertTrue(code)
                with sqlite3.connect(data_file) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],0)
                send('confirm '+code)
                read_until('operator> ')
                send('confirm '+code)
                self.assertIn('REFUSED:',read_until('operator> '))
                send('quit')
                read_until('Exiting operator console.')
                ended, status = os.waitpid(pid,0)
                self.assertEqual(os.waitstatus_to_exitcode(status),0)
                pid = None
                with sqlite3.connect(data_file) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT count(*) FROM pending_reviews').fetchone()[0],0)
            finally:
                if pid:
                    try: os.kill(pid,9)
                    except ProcessLookupError: pass
                    os.waitpid(pid,0)
                os.close(fd)
