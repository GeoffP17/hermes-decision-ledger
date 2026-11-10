"""Hermes native plugin entry point."""
from .decision_ledger.plugin import register

__all__ = ["register"]
