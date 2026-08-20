"""Offline-only ORQ-30 Stage 0 contracts.

This package constructs and validates local experiment inputs. It deliberately
contains no provider client, network adapter, dataset generator, or dispatcher.
"""

from .model import EvaluationStep, Event, Message

__all__ = ["EvaluationStep", "Event", "Message"]
