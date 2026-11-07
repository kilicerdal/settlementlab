"""Compatibility exports; prefer the layered implementation for new code."""

from .core.identity import Principal as Principal
from .core.identity import require as require
from .infrastructure.demo_sessions import PERSONAS as PERSONAS
from .infrastructure.demo_sessions import DemoSessions as DemoSessions
