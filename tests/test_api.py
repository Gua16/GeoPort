from contextlib import asynccontextmanager
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import main
from settings import SettingsStore
from location_service import LocationService
from test_location import FakeDevice, distance


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.temp.name)/'config.json')
        self.device = FakeDevice()
        self.service = LocationService(self.device.session)
        self.patches = [patch.object(main,'settings_store',self.store),patch.object(main,'location_service',self.service)]
        for p in self.patches: p.start()
        self.client = main.app.test_client()
        main.location = None
        main.rsd_data_map.clear()
        main.lockdown = None
    def tearDown(self):
        self.service.stop()
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def test_offline_ui_health_and_assets_do_not_request_internet_or_device(self):
        with patch.object(main.requests,'get',side_effect=AssertionError('Internet forbidden')) as network, \
             patch.object(main,'list_devices',side_effect=AssertionError('Device scan on response path')) as scan:
            for path in ['/', '/lite', '/health', '/static/lite.js', '/static/lite.css', '/api/settings']:
                response = self.client.get(path)
                self.assertEqual(response.status_code,200,path)
                response.close()
            html = self.client.get('/').text
            self.assertNotIn('https://',html)
            self.assertNotIn('http://',html)
            self.assertIn('/static/lite.js',html)
            self.assertIn('/static/lite.css',html)
            network.assert_not_called()
            scan.assert_not_called()

    def test_explicit_save_random_restore_stop_and_restart(self):
        base = {'lat':23.1291,'lng':113.2644}
        self.assertEqual(self.client.put('/api/base-location',json=base).status_code,200)
        self.client.put('/api/settings',json={'random_radius_m':300})
        self.service.connected({'udid':'fake'})
        for _ in range(10):
            response = self.client.post('/api/location/apply',json={'mode':'random'})
            self.assertEqual(response.status_code,200,response.json)
            self.assertLessEqual(distance(base,response.json['current_location']),300.00001)
            self.assertEqual(self.store.read()['base_location'],base)
        self.assertEqual(len(self.device.calls),10)
        self.assertEqual(self.device.opens,1)
        response = self.client.post('/api/location/apply',json={'mode':'base'})
        self.assertEqual(response.json['current_location'],base)
        self.assertEqual(self.client.post('/stop_location',json={}).status_code,200)
        self.assertIsNone(self.client.get('/api/settings').json['current_location'])
        restored = SettingsStore(self.store.path)
        self.assertEqual(restored.read()['base_location'],base)
        fresh_service = LocationService(self.device.session)
        self.assertEqual(fresh_service.state()['location_status'],'idle')
        self.assertIsNone(fresh_service.state()['current_location'])
        self.assertIsNone(fresh_service.state()['device_connection'])
        self.assertEqual(len(self.device.calls),11)

    def test_map_coordinates_not_saved_implicitly_and_legacy_api_shared(self):
        self.client.put('/api/base-location',json={'lat':1,'lng':2})
        self.assertEqual(self.client.post('/update_location',json={'lat':3,'lng':4}).status_code,200)
        self.service.connected({'udid':'fake'})
        response = self.client.post('/set_location',json={})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.device.calls,[(3,4)])
        self.assertEqual(self.store.read()['base_location'],{'lat':1,'lng':2})
        # Direct coordinates avoid the old two-request race in map mode.
        self.client.post('/set_location',json={'lat':5,'lng':6})
        self.assertEqual(self.device.calls[-1],(5,6))
        self.assertEqual(self.device.opens,1)
        self.device.fail_set = True
        self.assertEqual(self.client.post('/set_location',json={}).status_code,502)
        self.assertIsNone(self.client.get('/api/settings').json['current_location'])

    def test_missing_device_invalid_input_and_missing_base_are_errors(self):
        self.assertEqual(self.client.post('/api/location/apply',json={}).status_code,409)
        self.client.put('/api/base-location',json={'lat':1,'lng':2})
        self.assertEqual(self.client.post('/api/location/apply',json={}).status_code,409)
        for path,method,data in [('/api/base-location','put',{'lat':91,'lng':2}),
                                  ('/api/base-location','put',{'lat':'NaN','lng':2}),
                                  ('/api/base-location','put',[]),
                                  ('/api/settings','put',{'random_radius_m':-1}),
                                  ('/api/settings','put',{'base_location':None}),
                                  ('/api/location/apply','post',{'mode':'repeat'}),
                                  ('/connect_device','post',{'udid':'a','connType':'USB','ios_version':None})]:
            self.assertEqual(getattr(self.client,method)(path,json=data).status_code,400,(path,data))

    def test_settings_disk_failure_returns_error(self):
        with patch('settings.os.replace',side_effect=OSError('disk full')):
            self.assertEqual(self.client.put('/api/base-location',json={'lat':1,'lng':2}).status_code,503)
        self.assertIsNone(self.store.read()['base_location'])

    def test_connection_failure_and_tunnel_timeout_never_mark_connected(self):
        data = {'udid':'fake','connType':'USB','ios_version':'17.4'}
        with patch.object(main,'check_developer_mode',return_value=True), \
             patch.object(main,'create_using_usbmux',return_value=MagicMock()), \
             patch.object(main,'start_tcp_tunnel_thread'),patch.object(main,'check_rsd_data',return_value=False):
            response = self.client.post('/connect_device',json=data)
        self.assertEqual(response.status_code,502,response.json)
        self.assertIn('30 seconds',response.json['error'])
        self.assertIsNone(self.service.state()['device_connection'])

    def test_developer_mode_required_is_not_a_connection_success(self):
        with patch.object(main,'check_developer_mode',return_value=False):
            response = self.client.post('/connect_device',json={'udid':'fake','connType':'USB','ios_version':'17.4'})
        self.assertEqual(response.status_code,409)
        self.assertIn('developer_mode_required',response.json)
        self.assertIsNone(self.service.state()['device_connection'])

    def test_original_ios16_adapter_set_stop_and_disconnect(self):
        # Exercise the real connection and location adapter with transport fakes.
        data = {'udid':'fake','connType':'USB','ios_version':'16.6'}
        mock_lockdown = MagicMock()
        with patch.object(main,'check_developer_mode',return_value=True), \
             patch.object(main,'create_using_usbmux',return_value=mock_lockdown), \
             patch.object(main,'auto_mount') as mount, \
             patch.object(main,'DvtSecureSocketProxyService') as dvt, \
             patch.object(main,'LocationSimulation',return_value=self.device):
            adapter = LocationService(main.device_location_session)
            with patch.object(main,'location_service',adapter):
                response = self.client.post('/connect_device',json=data)
                self.assertEqual(response.status_code,200,response.json)
                self.client.post('/update_location',json={'lat':1,'lng':2})
                response = self.client.post('/set_location',json={})
                self.assertEqual(response.status_code,200,response.json)
                self.client.post('/set_location',json={'lat':3,'lng':4})
                self.assertEqual(self.device.calls,[(1,2),(3,4)])
                mount.assert_called_once_with(mock_lockdown)
                dvt.assert_called_once_with(lockdown=mock_lockdown)
                response = self.client.post('/api/device/disconnect',json={})
                self.assertEqual(response.status_code,200,response.json)
                self.assertIsNone(adapter.state()['device_connection'])
                dvt.return_value.__exit__.assert_called_once()

    def test_original_ios17_adapter_retains_rsd_session(self):
        @asynccontextmanager
        async def remote(address):
            self.assertEqual(address,('::1',1234))
            yield 'remote'
        main.udid,main.ios_version,main.connection_type = 'fake','17.4','USB'
        main.rsd_data_map['fake'] = {'USB':{'host':'::1','port':'1234'}}
        with patch.object(main,'RemoteServiceDiscoveryService',side_effect=remote), \
             patch.object(main,'DvtSecureSocketProxyService') as dvt, \
             patch.object(main,'LocationSimulation',return_value=self.device):
            adapter = LocationService(main.device_location_session)
            adapter.connected({'udid':'fake'})
            try:
                adapter.apply({'lat':1,'lng':2})
                adapter.apply({'lat':3,'lng':4})
                dvt.assert_called_once_with('remote')
                self.assertEqual(self.device.calls,[(1,2),(3,4)])
            finally: adapter.stop()
            dvt.return_value.__exit__.assert_called_once()

    def test_map_available_and_mode_preference_persists(self):
        with patch.object(main,'start_online_data'):
            response = self.client.get('/map')
        self.assertEqual(response.status_code,200)
        self.assertIn('id="map"',response.text)
        self.assertIn('保存为基准坐标',response.text)
        self.client.put('/api/settings',json={'ui_mode':'map'})
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.client.get('/lite').status_code,200)

    def test_exit_clears_the_session_and_acknowledges_before_process_exit(self):
        self.service.connected({'udid':'fake'})
        self.service.apply({'lat':1,'lng':2})
        with patch.object(main.threading,'Thread') as thread, patch.object(main.os,'_exit') as exit_process:
            response = self.client.post('/exit',json={})
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(response.json['success'])
        self.assertEqual(self.device.clears,1)
        self.assertEqual(self.device.closes,1)
        self.assertIsNone(self.service.state()['device_connection'])
        self.assertEqual(thread.call_args.kwargs['name'],'GeoPort-exit')
        thread.return_value.start.assert_called_once()
        exit_process.assert_not_called()
