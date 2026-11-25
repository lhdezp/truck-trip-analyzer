"""Application layer: contracts and use cases.

Contracts here are the boundary between interfaces (FastAPI, Telegram) and the
engine. They may import the domain; they must never import a provider SDK.
"""
