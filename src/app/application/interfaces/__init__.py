"""Ports (interfaces) implemented by infrastructure adapters.

The application layer owns these contracts. Adapters depend on them, never the other
way round, which is what keeps Gemini, HTTPX and SQLAlchemy out of the domain.
"""
