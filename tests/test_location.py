import asyncio
from contextlib import asynccontextmanager
import math
from pathlib import Path
import random
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from location_math import coordinates, random_offset, EARTH_RADIUS_M
from location_service import LocationService, LocationError


def distance(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2-lat1
    dlng = math.radians(b['lng']-a['lng'])
    h = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
    return EARTH_RADIUS_M*2*math.atan2(math.sqrt(max(0,h)), math.sqrt(max(0,1-h)))


class MathTests(unittest.TestCase):
    def test_1000_offsets_within_radius_and_no_drift(self):
        for centre in [{'lat':23.1291,'lng':113.2644}, {'lat':89.9999,'lng':179.9999},
                       {'lat':90,'lng':180}, {'lat':-90,'lng':-180}]:
            rng = random.Random(47)
            squared = []
            original = centre.copy()
            for _ in range(1000):
                point = random_offset(centre, 300, rng)
                d = distance(centre, point)
                self.assertLessEqual(d,300.00001)
                self.assertEqual(centre,original)
                self.assertLessEqual(abs(point['lng']),180)
                squared.append((d/300)**2)
            self.assertAlmostEqual(sum(squared)/1000,0.5,delta=0.025)

    def test_invalid_coordinates_and_zero_radius(self):
        for lat,lng in [(91,0),(0,181),(float('nan'),0),(0,float('inf')),(True,1),(None,2)]:
            with self.assertRaises(ValueError): coordinates(lat,lng)
        centre = {'lat':1,'lng':2}
        self.assertEqual(random_offset(centre,0),centre)
        for radius in [-1,100001,float('nan')]:
            with self.assertRaises(ValueError): random_offset(centre,radius)


class FakeDevice:
    def __init__(self):
        self.opens = self.closes = self.clears = 0
        self.calls = []
        self.fail_set = self.fail_clear = False
        self.started = threading.Event()
        self.release = None

    @asynccontextmanager
    async def session(self):
        self.opens += 1
        try: yield self
        finally: self.closes += 1

    def set(self, lat, lng):
        self.started.set()
        if self.release: self.release.wait(2)
        if self.fail_set: raise OSError('device disconnected')
        self.calls.append((lat,lng))

    def clear(self):
        if self.fail_clear: raise OSError('clear failed')
        self.clears += 1


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.device = FakeDevice()
        self.service = LocationService(self.device.session)
        self.service.connected({'udid':'test-device'})

    def tearDown(self):
        self.device.fail_clear = False
        self.service.stop()

    def test_updates_reuse_one_session_and_close_on_stop(self):
        for i in range(8): self.service.apply({'lat':i,'lng':i})
        self.assertEqual(self.device.opens,1)
        self.assertEqual(len(self.device.calls),8)
        self.assertEqual(self.device.closes,0)
        self.assertEqual(self.service.state()['current_location'],{'lat':7,'lng':7})
        self.service.stop()
        self.assertEqual(self.device.clears,1)
        self.assertEqual(self.device.closes,1)
        self.assertIsNone(self.service.state()['current_location'])
        self.assertEqual(self.service.state()['location_status'],'idle')
        self.service.apply({'lat':3,'lng':4})
        self.assertEqual(self.device.opens,2)

    def test_device_failure_does_not_report_success_or_stale_location(self):
        self.service.apply({'lat':1,'lng':2})
        self.device.fail_set = True
        with self.assertRaises(LocationError): self.service.apply({'lat':3,'lng':4})
        state = self.service.state()
        self.assertEqual(state['location_status'],'failed')
        self.assertIsNone(state['current_location'])
        self.assertIsNone(state['device_connection'])
        self.assertEqual(self.device.closes,1)
        with self.assertRaises(LocationError): self.service.apply({'lat':5,'lng':6})

    def test_failed_session_creation_finishes_request(self):
        @asynccontextmanager
        async def broken():
            raise OSError('session unavailable')
            yield
        service = LocationService(broken)
        service.connected({'udid':'missing'})
        with self.assertRaises(LocationError): service.apply({'lat':1,'lng':2})
        service.stop()
        self.assertIsNone(service.state()['current_location'])

    def test_failed_clear_does_not_report_stopped(self):
        self.service.apply({'lat':1,'lng':2})
        self.device.fail_clear = True
        with self.assertRaises(LocationError): self.service.stop()
        self.assertEqual(self.service.state()['location_status'],'failed')
        self.assertEqual(self.device.closes,1)
        self.assertIsNone(self.service.state()['current_location'])

    def test_concurrent_apply_stop_and_connection_change_rejected(self):
        self.device.release = threading.Event()
        errors = []
        def apply():
            try: self.service.apply({'lat':1,'lng':2})
            except Exception as error: errors.append(error)
        thread = threading.Thread(target=apply)
        thread.start()
        self.assertTrue(self.device.started.wait(2))
        self.assertEqual(self.service.state()['location_status'],'processing')
        self.assertIsNone(self.service.state()['current_location'])
        try:
            for operation in [lambda:self.service.apply({'lat':3,'lng':4}), self.service.stop]:
                with self.assertRaises(LocationError): operation()
            with self.assertRaises(LocationError):
                with self.service.connection_change(): pass
        finally:
            self.device.release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(self.device.calls,[(1,2)])

    def test_connection_change_clears_previous_device_and_location(self):
        self.service.apply({'lat':1,'lng':2})
        with self.service.connection_change(): self.service.connected({'udid':'second'})
        self.assertEqual(self.device.clears,1)
        self.assertEqual(self.service.state()['device_connection']['udid'],'second')
        self.assertIsNone(self.service.state()['current_location'])

    def test_stop_clears_a_reconnected_device_without_applying_a_point(self):
        self.service.stop()
        self.assertEqual(self.device.calls,[])
        self.assertEqual(self.device.clears,1)
        self.assertEqual(self.device.closes,1)
        self.service.stop()
        self.assertEqual(self.device.opens,1)
