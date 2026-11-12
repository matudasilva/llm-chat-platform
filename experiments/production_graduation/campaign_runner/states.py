from enum import StrEnum


class State(StrEnum):
    INIT = "INIT"
    PREFLIGHT = "PREFLIGHT"
    READY = "READY"
    IN_FLIGHT = "IN_FLIGHT"
    SETTLE = "SETTLE"
    COMPLETE = "COMPLETE"
    INCOMPLETE_STOP_RETRY = "INCOMPLETE_STOP_RETRY"
    INCOMPLETE_STOP_EVALUATOR = "INCOMPLETE_STOP_EVALUATOR"
    INCOMPLETE_BUDGET = "INCOMPLETE_BUDGET"
    FAILED = "FAILED"


TERMINAL = frozenset({State.COMPLETE, State.INCOMPLETE_STOP_RETRY,
                      State.INCOMPLETE_STOP_EVALUATOR, State.INCOMPLETE_BUDGET,
                      State.FAILED})
NEXT = {
    State.INIT: {State.PREFLIGHT},
    State.PREFLIGHT: {State.READY, State.FAILED},
    State.READY: {State.IN_FLIGHT, *TERMINAL},
    State.IN_FLIGHT: {State.SETTLE, State.FAILED},
    State.SETTLE: {State.READY, *TERMINAL},
}


def transition(current: State, target: State) -> State:
    if target not in NEXT.get(current, set()):
        raise ValueError(f"Invalid transition: {current} -> {target}")
    return target
