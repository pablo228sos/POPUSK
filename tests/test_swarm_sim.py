import unittest
from PyQt6.QtCore import QCoreApplication
import sys

app = QCoreApplication.instance()
if not app:
    app = QCoreApplication(sys.argv)

from teknofest_gcs.core.models import FleetManager
from teknofest_gcs.core.sim import SwarmSimulationEngine

class TestSwarmSimulation(unittest.TestCase):
    def setUp(self):
        self.fleet = FleetManager()
        self.sim = SwarmSimulationEngine(self.fleet)

    def test_configure_swarm(self):
        self.sim.configure_swarm(5)
        self.assertEqual(len(self.sim.vehicles), 5)
        self.assertEqual(len(self.fleet.all_vehicles()), 5)
        
        # Check that drone IDs are assigned correctly starting from 101
        self.assertIn(101, self.sim.vehicles)
        self.assertIn(105, self.sim.vehicles)

    def test_vehicle_state_transitions(self):
        self.sim.configure_swarm(1)
        v = self.sim.vehicles[101]
        self.assertEqual(v.flight_mode, "LANDED")
        self.assertFalse(v.armed)

        # Arm
        self.sim.send_vehicle_command(101, "arm")
        self.assertTrue(v.armed)
        self.assertEqual(v.flight_mode, "ARMED")

        # Takeoff
        self.sim.send_vehicle_command(101, "takeoff")
        self.assertEqual(v.flight_mode, "TAKEOFF")
        self.assertEqual(v.target_alt, 15.0)

        # Sim update tick
        v.update(1.0) # Tick 1 second
        self.assertGreater(v.alt, 0.0)

if __name__ == "__main__":
    unittest.main()
