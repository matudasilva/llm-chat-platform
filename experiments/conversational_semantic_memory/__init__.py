"""Offline ORQ-39 experiment: conversational semantic memory.

Compares a recent window plus E-BM25 (an experimental configuration with its
flags on, not a validated baseline), the same plus direct dense retrieval over
turns, and the same plus extracted, conversation-scoped semantic facts. Nothing
under `app/` imports this package, and nothing here changes runtime behaviour.
"""
