from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MissionState(str, Enum):
    INIT = "INIT"
    CONNECTED = "CONNECTED"
    ARMED = "ARMED"
    MISSION = "MISSION"
    FAILSAFE = "FAILSAFE"
    RTL = "RTL"


class MissionEvent(str, Enum):
    LINK_ESTABLISHED = "LINK_ESTABLISHED"
    ARM = "ARM"
    DISARM = "DISARM"
    START_MISSION = "START_MISSION"
    LINK_LOST = "LINK_LOST"
    TRIGGER_RTL = "TRIGGER_RTL"
    RECOVER = "RECOVER"
    RESET = "RESET"


TRANSITIONS: dict[MissionState, dict[MissionEvent, MissionState]] = {
    MissionState.INIT: {
        MissionEvent.LINK_ESTABLISHED: MissionState.CONNECTED,
        MissionEvent.RESET: MissionState.INIT,
    },
    MissionState.CONNECTED: {
        MissionEvent.ARM: MissionState.ARMED,
        MissionEvent.LINK_LOST: MissionState.FAILSAFE,
        MissionEvent.RESET: MissionState.INIT,
    },
    MissionState.ARMED: {
        MissionEvent.START_MISSION: MissionState.MISSION,
        MissionEvent.DISARM: MissionState.CONNECTED,
        MissionEvent.LINK_LOST: MissionState.FAILSAFE,
        MissionEvent.TRIGGER_RTL: MissionState.RTL,
    },
    MissionState.MISSION: {
        MissionEvent.LINK_LOST: MissionState.FAILSAFE,
        MissionEvent.TRIGGER_RTL: MissionState.RTL,
        MissionEvent.DISARM: MissionState.CONNECTED,
    },
    MissionState.FAILSAFE: {
        MissionEvent.TRIGGER_RTL: MissionState.RTL,
        MissionEvent.RECOVER: MissionState.CONNECTED,
        MissionEvent.RESET: MissionState.INIT,
    },
    MissionState.RTL: {
        MissionEvent.DISARM: MissionState.CONNECTED,
        MissionEvent.RESET: MissionState.INIT,
    },
}


@dataclass(slots=True)
class TransitionResult:
    previous: MissionState
    current: MissionState
    event: MissionEvent


class InvalidTransitionError(RuntimeError):
    pass


class MissionStateMachine:
    def __init__(self) -> None:
        self._state = MissionState.INIT

    @property
    def state(self) -> MissionState:
        return self._state

    def can_apply(self, event: MissionEvent) -> bool:
        return event in TRANSITIONS[self._state]

    def apply(self, event: MissionEvent) -> TransitionResult:
        if event not in TRANSITIONS[self._state]:
            raise InvalidTransitionError(f"Transition {event.value} is not allowed from {self._state.value}")
        previous = self._state
        self._state = TRANSITIONS[self._state][event]
        return TransitionResult(previous=previous, current=self._state, event=event)
