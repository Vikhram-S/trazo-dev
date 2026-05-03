"""
Trazo.integrations
~~~~~~~~~~~~~~~~~~~~~~
Auto-instrumentation patches for popular LLM SDKs.
"""

from __future__ import annotations

from .openai_patch import patch_openai

__all__ = ["patch_openai"]
