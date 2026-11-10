"""Authenticated GET-only dashboard surface; all storage access is read-only."""
from fastapi import APIRouter, HTTPException, Query
from hermes_constants import get_hermes_home
# Dashboard APIs load by file path, independently of the tool module's namespace.
import importlib.util
import importlib
import sys
from pathlib import Path
_package = "_decision_ledger_board"
if _package not in sys.modules:
    _root = Path(__file__).resolve().parent.parent / "decision_ledger"
    _spec = importlib.util.spec_from_file_location(_package, _root / "__init__.py", submodule_search_locations=[str(_root)])
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_package] = _module
    _spec.loader.exec_module(_module)
ReceiptReader = importlib.import_module(_package + ".reader").ReceiptReader
LedgerError = importlib.import_module(_package + ".core").LedgerError
import sqlite3

router = APIRouter()

@router.get('/receipts')
def receipts(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=100)):
    try:
        return ReceiptReader(get_hermes_home() / 'plugin-data' / 'decision-ledger' / 'ledger.sqlite3').page(offset, limit)
    except (LedgerError, sqlite3.Error, OSError) as error:
        raise HTTPException(status_code=409, detail='The ledger could not be read. No records were changed.') from error
