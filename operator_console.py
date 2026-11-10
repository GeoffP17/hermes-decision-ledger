#!/usr/bin/env python3
"""Decision Ledger 0.3.1 local operator console (experimental).

This is an independent terminal entrypoint, NOT a gateway/desktop plugin command.
Run directly as the profile data owner with a foreground TTY.
Does not give the gateway a new approval route; never accepts command-line actions.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import secrets
import shlex
import sqlite3
import sys
import traceback

PLUGIN_ROOT = Path(__file__).resolve().parent
DB_PATH = PLUGIN_ROOT.parent.parent / 'plugin-data' / 'decision-ledger' / 'ledger.sqlite3'
UID = os.getuid()
EXPECTED = {
    'plugin.yaml': '01e02c9733c2bdfc9cdd1c557922e309ec40432f5b7408e7225e50ea76d0c39c',
    'decision_ledger/core.py': 'b485d4de3c4ae332dbdc656b2cf8aa23e6999f308b76ffe7c5967aa6dcefa404',
    'decision_ledger/plugin.py': '3c397a4739a96aa23876db3321e540876f9445df1274b502033103016f76b5ba',
}
HELP = '''Commands (at operator> prompt):
  list [PROJECT [TOPIC]]
  show ID
  approve ID:DIGEST [replace OLD_ID:OLD_DIGEST]
  reject ID:DIGEST
  revoke ID:DIGEST
  satisfy ID:DIGEST EVIDENCE_NOTE_FOR_ALL_CONDITIONS
  confirm REVIEW_CODE     (only after inspecting exact PREVIEW)
  cancel REVIEW_CODE
  help
  quit

Every state change is a TWO-STEP review then confirmation in the SAME terminal session.
This tool records operator intent; it does not run deployments or prove a human identity.
Untrusted proposed text is escaped/indented by the installed v0.3.1 code.
'''


def require_terminal():
    if os.name != 'posix' or os.getuid() != UID or os.geteuid() != UID:
        raise RuntimeError('Refusing: real/effective UID must match the profile data owner')
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError('Refusing: a real interactive terminal is required; noninteractive pipes are not supported')
    try:
        fd = os.open('/dev/tty', os.O_RDWR | getattr(os, 'O_NOCTTY', 0))
        try:
            if os.tcgetpgrp(fd) != os.getpgrp():
                raise RuntimeError('Refusing: process is not in the foreground terminal process group')
        finally:
            os.close(fd)
    except OSError as error:
        raise RuntimeError('Refusing: cannot access a controlling terminal') from error


def require_installed_files():
    root = PLUGIN_ROOT
    if Path(__file__).is_symlink():
        raise RuntimeError('Refusing: operator entrypoint may not be a symlink')
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError('Refusing: installed plugin directory missing or symlinked')
    for rel, want in EXPECTED.items():
        path = root / rel
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Refusing: installed runtime file missing or symlinked: ' + rel)
        if hashlib.sha256(path.read_bytes()).hexdigest() != want:
            raise RuntimeError('Refusing: installed runtime hash mismatch: ' + rel)
    if not DB_PATH.is_file() or DB_PATH.is_symlink():
        raise RuntimeError('Refusing: production ledger DB missing or symlinked')
    if DB_PATH.stat().st_uid != UID:
        raise RuntimeError('Refusing: production ledger DB has unexpected owner')


def operator_factory(ledger_path):
    from decision_ledger.core import Ledger
    from decision_ledger.plugin import Service
    return LocalOperator(Service(Ledger(ledger_path)), 'terminal-local-' + secrets.token_hex(18))


class LocalOperator:
    """Standalone trust boundary: caller must establish a verified local operator terminal.

    Unlike Service.command, this does not claim platform='cli'/source=None for gateway RPC.
    It reuses the installed exact-preview + persisted confirmation functions directly.
    """
    def __init__(self, service, session_id):
        self.service = service
        self.ledger = service.ledger
        self.session_id = session_id
        self.active_code = None

    def run_command(self, raw):
        from decision_ledger.core import LedgerError
        from decision_ledger.plugin import card
        words = shlex.split(raw)
        if not words:
            return ''
        action = words.pop(0).lower()
        if action in ('quit', 'exit'):
            if words:
                raise LedgerError('quit accepts no arguments')
            return None
        if action == 'help':
            return HELP
        if action == 'list' and len(words) <= 2:
            response = self.ledger.list(*(words + [None] * (2-len(words))))
            return '\n\n'.join([f"Registered decisions ({response['total']} total; historical completeness unknown):"] +
                                [card(self.service.view(item)) for item in response['decisions']])
        if action == 'show' and len(words) == 1:
            return card(self.service.view(self.ledger.get(words[0].split(':', 1)[0])))
        if action == 'cancel' and len(words) == 1:
            if self.active_code != words[0]:
                raise LedgerError('refusing: only this terminal session’s current preview can be canceled')
            changed = self.ledger.cancel_review(words[0], self.session_id)
            self.active_code = None
            return 'Review canceled; no decision changed.' if changed else 'No matching pending review.'
        if action == 'confirm' and len(words) == 1:
            if self.active_code != words[0]:
                raise LedgerError('refusing: only the preview shown in this foreground terminal can be confirmed')
            # Explicit separate terminal input; re-checks preview, event revision, token, nonce and TTL in SQLite.
            result = self.service._confirm(words[0], self.session_id)
            self.active_code = None
            return result + '\nDecision state updated by local operator terminal.'
        if action not in ('approve', 'reject', 'revoke', 'satisfy') or not words:
            raise LedgerError('Unrecognized or incomplete command. Enter ONE command line only; type help for the command list.')
        token = words.pop(0)
        replace = note = None
        if action == 'approve' and words:
            if len(words) != 2 or words[0] != 'replace':
                raise LedgerError('usage: approve NEW_TOKEN replace OLD_TOKEN')
            replace = words[1]
        elif action == 'satisfy':
            note = ' '.join(words)
            if not note.strip():
                raise LedgerError('satisfy requires an evidence note')
        elif words:
            raise LedgerError('unexpected trailing words')
        item = self.ledger.get(token.split(':', 1)[0])
        # The standalone console intentionally has no native SessionDB evidence reader.
        # Never accept sourced approvals when the original exchange is unavailable to verify.
        if item.get('evidence'):
            raise LedgerError('refusing sourced decision: original conversation cannot be verified in standalone console')
        code, preview = self.service._prepare(token, action, self.session_id, raw, replace, note)
        self.active_code = code
        return (preview + '\n\nStandalone operator: use ONLY the exact confirm/cancel commands below in this same session.\n'
                + '\n--- NO RECEIPT STATE HAS CHANGED ---\n'
                'Inspect the exact scope, exclusions, conditions and any replacement above.\n'
                'Type CONFIRM ONLY IF YOU INTEND TO RECORD THIS DECISION:\n'
                '  confirm ' + code + '\n'
                'Or type:\n  cancel ' + code + '\n'
                'Expires in 15 minutes; review is bound to this terminal session.')


def main():
    require_terminal()
    require_installed_files()
    # Avoid import confusion from current directory or another plugin installation.
    sys.path.insert(0, str(PLUGIN_ROOT))
    operator = operator_factory(DB_PATH)
    print('Decision Ledger 0.3.1 — SEPARATE LOCAL OPERATOR CONSOLE')
    print('Verified installed runtime hashes. Local checks: owner UID + foreground TTY.')
    print('Not registered as an AI tool; same-UID code can still bypass this console. No cryptographic human authentication.')
    print('It writes a pending preview challenge only when requested; final receipts require confirm CODE.')
    print(HELP)
    print('Paste exactly ONE command line at a time; never paste terminal output or multiple commands.')
    try:
        while True:
            try:
                line = input('operator> ')
            except (KeyboardInterrupt, EOFError):
                print('\nExiting; no pending decision is automatically confirmed.')
                return 0
            try:
                result = operator.run_command(line)
                if result is None:
                    print('Exiting operator console.')
                    return 0
                if result:
                    print(result)
            except (ValueError, TypeError, KeyError, sqlite3.Error, OSError, RuntimeError) as e:
                print('REFUSED: ' + str(e))
    finally:
        if operator.active_code:
            operator.ledger.cancel_review(operator.active_code, operator.session_id)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as e:
        print('LOCAL OPERATOR NOT STARTED: ' + str(e), file=sys.stderr)
        raise SystemExit(1)
