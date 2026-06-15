import unittest
from PyQt6.QtCore import QCoreApplication
import sys

app = QCoreApplication.instance()
if not app:
    app = QCoreApplication(sys.argv)

from teknofest_gcs.core.models import FleetManager, VehicleState

class TestSwarmModel(unittest.TestCase):
    def setUp(self):
        self.fleet = FleetManager()
        self.added = []
        self.fleet.vehicle_added.connect(self.added.append)

    def test_update_and_signals(self):
        self.fleet.update_vehicle(101, lat=41.0, lon=29.0)
        self.assertEqual(len(self.fleet.all_vehicles()), 1)
        self.assertEqual(self.added, [101])
        
        v = self.fleet.get_vehicle(101)
        self.assertEqual(v.lat, 41.0)
        self.assertEqual(v.lon, 29.0)
        
        self.fleet.update_vehicle(101, armed=True)
        self.assertTrue(v.armed)

if __name__ == "__main__":
    unittest.main()
