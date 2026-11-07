"""Compatibility exports; prefer the layered implementation for new code."""

from .adapters.ai import INSTRUCTIONS as INSTRUCTIONS
from .adapters.ai import SCHEMA as SCHEMA
from .adapters.ai import Triage as Triage
from .adapters.ai import send_request as send_request
from .core.evidence import build_evidence as build_evidence
