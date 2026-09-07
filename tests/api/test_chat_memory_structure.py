"""ORQ-37 T9 — AC11's Gate B1 half, as a property of the source, not of review.

Separate module from `test_chat_memory_dependency.py` because these are
synchronous and that file carries a module-wide `asyncio` mark.
"""
from __future__ import annotations

import inspect

from app.api.deps import get_chat_memory_context
from app.core.settings import settings as real_settings


# --- AC11 history half: the assembly is structurally outside the transaction


def test_is_a_coroutine_dependency() -> None:
    # AC26 also requires this: a *sync* dependency runs in a threadpool under a
    # copied context, where the collector's `ContextVar.set()` would silently
    # fail to propagate.
    assert inspect.iscoroutinefunction(get_chat_memory_context)


def test_dependency_takes_no_db_session() -> None:
    # The regression this pins: someone adds `db: AsyncSession = Depends(get_db)`
    # to reuse the primary session. That would put a best-effort read on the
    # pool the atomic write needs and, worse, make the assembly reachable from
    # inside the handler's transaction.
    parameters = inspect.signature(get_chat_memory_context).parameters
    assert set(parameters) == {"payload", "request"}


def test_route_resolves_memory_as_a_dependency() -> None:
    # AC11's B1 half is satisfied *by construction* only if the assembly is a
    # dependency: dependencies resolve before the handler body, hence before
    # either `async with db.begin()`.
    from app.api.routes import chat as chat_route

    source = inspect.getsource(chat_route.chat)
    assert "Depends(get_chat_memory_context)" in source
    # And it must not be invoked from inside the handler body.
    assert "await get_chat_memory_context(" not in source


def test_history_assembly_is_not_inside_any_transaction_block() -> None:
    """AC11 read as a property of the file, not of a reviewer's attention."""
    from app.api.routes import chat as chat_route

    lines = inspect.getsource(chat_route).splitlines()
    depth_stack: list[int] = []
    offenders: list[int] = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        while depth_stack and indent <= depth_stack[-1]:
            depth_stack.pop()
        if stripped.startswith("async with db.begin()"):
            depth_stack.append(indent)
            continue
        if depth_stack and ("memory_context" in stripped or "memory_messages" in stripped):
            offenders.append(number)
    assert offenders == [], f"memory touched inside db.begin() at lines {offenders}"



def test_shipped_default_is_off() -> None:
    assert real_settings.conversation_history_enabled is False
