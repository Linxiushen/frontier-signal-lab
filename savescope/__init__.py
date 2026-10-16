"""Saved-tensor scope diagnostics. ML dependencies load only when audit runs."""

from .audit import SavedTensorPolicy, SaveScopeError, audit

__all__ = ["SavedTensorPolicy", "SaveScopeError", "audit"]
__version__ = "0.1.0"
