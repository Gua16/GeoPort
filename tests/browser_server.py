"""Local fake-device fixture for browser acceptance tests; never use as the app launcher."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import main
from test_location import FakeDevice
from location_service import LocationService

device = FakeDevice()
main.location_service = LocationService(device.session)
main.list_devices = lambda: []


@main.app.route('/test/calls')
def calls():
    return main.jsonify({'sets': device.calls, 'opens': device.opens, 'closes': device.closes})


@main.app.route('/test/fail', methods=['POST'])
def fail():
    device.fail_set = True
    return main.jsonify({'success': True})


def connect():
    data = main.json_body()
    main.rsd_data_map[data['udid']] = {data['connType']: {'host': '::1', 'port': 1234}}
    return main.jsonify({'rsd_data': ['::1', 1234]})


main.connect_device_legacy = connect


@main.app.route('/test/devices')
def devices():
    return main.jsonify({'test-phone': {'USB': [{'DeviceName': 'Test iPhone', 'ProductVersion': '17.4'}]}})


if __name__ == '__main__':
    # Replace the scan view only in this standalone test server.
    main.app.view_functions['py_list_devices'] = devices
    main.app.run(host='127.0.0.1', port=int(sys.argv[1]), debug=False, use_reloader=False)
