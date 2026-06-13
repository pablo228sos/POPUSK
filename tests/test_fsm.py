import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from teknofest_gcs.mission.fsm import InvalidTransitionError, MissionEvent, MissionState, MissionStateMachine


class MissionStateMachineTests(unittest.TestCase):
    def test_happy_path(self) -> None:
        fsm = MissionStateMachine()
        fsm.apply(MissionEvent.LINK_ESTABLISHED)
        fsm.apply(MissionEvent.ARM)
        result = fsm.apply(MissionEvent.START_MISSION)
        self.assertEqual(result.current, MissionState.MISSION)

    def test_invalid_transition_raises(self) -> None:
        fsm = MissionStateMachine()
        with self.assertRaises(InvalidTransitionError):
            fsm.apply(MissionEvent.START_MISSION)

    def test_link_loss_goes_to_failsafe(self) -> None:
        fsm = MissionStateMachine()
        fsm.apply(MissionEvent.LINK_ESTABLISHED)
        result = fsm.apply(MissionEvent.LINK_LOST)
        self.assertEqual(result.current, MissionState.FAILSAFE)


if __name__ == "__main__":
    unittest.main()
