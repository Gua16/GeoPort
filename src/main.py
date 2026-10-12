import locale
import os
import re
import sys
import time
import pyuac
import psutil
import signal
import socket
import random
import asyncio
import argparse
import requests
import threading
import webbrowser
import subprocess
import pycountry
from urllib.request import urlopen

from location_math import coordinates, random_offset
from location_service import LocationError, LocationService
from settings import SettingsStore

from flask import Flask, jsonify, render_template, request, redirect
from urllib3.exceptions import InsecureRequestWarning, ConnectionError
from contextlib import asynccontextmanager

from pymobiledevice3.usbmux import list_devices
from pymobiledevice3.cli.mounter import auto_mount
from pymobiledevice3.lockdown import create_using_usbmux, create_using_tcp, get_mobdev2_lockdowns
from pymobiledevice3.services.amfi import AmfiService
from pymobiledevice3.exceptions import DeviceHasPasscodeSetError, NoDeviceConnectedError
from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService
from pymobiledevice3.services.dvt.instruments.location_simulation import LocationSimulation
from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
from pymobiledevice3.remote.utils import stop_remoted_if_required, resume_remoted_if_required, get_rsds
from pymobiledevice3.remote.tunnel_service import create_core_device_tunnel_service_using_rsd, get_remote_pairing_tunnel_services, start_tunnel, create_core_device_tunnel_service_using_remotepairing, get_core_device_tunnel_services, CoreDeviceTunnelProxy
#from pymobiledevice3.cli.remote import install_driver_if_required
from pymobiledevice3.osu.os_utils import get_os_utils
from pymobiledevice3.bonjour import DEFAULT_BONJOUR_TIMEOUT, browse_mobdev2
from pymobiledevice3.pair_records import get_local_pairing_record, get_remote_pairing_record_filename, get_preferred_pair_record
from pymobiledevice3.common import get_home_folder
from pymobiledevice3.cli.remote import cli_install_wetest_drivers

from pymobiledevice3.cli.remote import tunnel_task
from pymobiledevice3.lockdown import LockdownClient
from pymobiledevice3.lockdown_service_provider import LockdownServiceProvider
from pymobiledevice3.remote.common import TunnelProtocol

#========= Arg Parser ========
# Parse command-line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--no-browser', action='store_true', help='Skip auto opening the browser')
parser.add_argument('--port', type=int, help='Specify port number to listen on for web browser requests')
parser.add_argument('--wifihost', type=str, help='Specify the wifi IP address to connect to')
parser.add_argument('--udid', type=str, help='Specify the device udid to target')
parser.add_argument('--ui-mode', choices=('lite', 'map'), help='Override the saved startup interface')
args = parser.parse_args() if __name__ == '__main__' else parser.parse_args([])
#========= Arg Parser ========

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
OSUTILS = get_os_utils()


import logging


# Get or create a logger instance named "GeoPort"
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Create a logger named "GeoPort"
logger = logging.getLogger("GeoPort")
logging.getLogger("urllib3").setLevel(logging.WARNING)

logging.getLogger('werkzeug').disabled = True
#log.disabled = True

app = Flask(__name__)
settings_store = SettingsStore()

# Define constants
# Get the home directory of the current user
home_dir = os.path.expanduser("~")
is_windows = sys.platform == 'win32'
base_directory = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(sys.argv[0])))
flask_port = 54321
api_url = "https://projectzerothree.info/api.php?format=json"
api_data = None
user_locale = None
location = None
rsd_data = None
rsd_host = None
rsd_port = None
rsd_data_map = {}
wifi_address = None
wifihost = args.wifihost
wifi_port = None
connection_type = None
udid = None
lockdown = None
ios_version = None
pair_record = None
error_message = None
sudo_message = ""
captured_output = None
GITHUB_REPO = 'davesc63/GeoPort'
CURRENT_VERSION_FILE = 'CURRENT_VERSION'
BROADCAST_FILE = 'BROADCAST'
APP_VERSION_NUMBER = "2.3.3"
APP_VERSION_TYPE = "fuel"
terminate_tunnel_thread = False
terminate_location_thread = False
location_threads = []
tunnel_threads = []
online_started = False
online_lock = threading.Lock()
online_metadata = {'version': None, 'broadcast': None, 'complete': False}
timeout = DEFAULT_BONJOUR_TIMEOUT

# Get the current platform using sys.platform
current_platform = sys.platform

# Map the platform names to standard values
platform = {
    'win32': 'Windows',
    'linux': 'Linux',
    'darwin': 'MacOS',
}.get(current_platform, 'Unknown')

# Check if running as sudo
if current_platform == "darwin":
    if os.geteuid() != 0:
        logger.error("*********************** WARNING ***********************")
        logger.error("Not running as Sudo, this probably isn't going to work")
        logger.error("*********************** WARNING ***********************")
        sudo_message = "Not running as Sudo, this probably isn't going to work"
    else:
        logger.info("Running as Sudo")
        sudo_message = ""



def fetch_api_data(api_url):
    global api_data
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        api_data = response.json()
        return api_data
    except (requests.exceptions.RequestException, ValueError) as e:
        logger.error(f"Error: {e}")
        logger.error(f"API is unreachable or there was an error during the request")
        logger.error("Sorry - Fuel data is not available")
        return None
    except ConnectionError as e:
        logger.error("Error: Name resolution failed.")
        logger.error("Please check your internet connection or the correctness of the API URL.")
        logger.error("Sorry - Fuel data is not available")
        logger.error(f"Details: {e}")
        return None

def create_geoport_folder():
    # Define the path to the GeoPort folder
    geoport_folder = os.path.join(home_dir, 'GeoPort')

    # Check if the GeoPort folder exists, create it if not
    if not os.path.exists(geoport_folder):
        os.makedirs(geoport_folder)
        logger.info(f"GeoPort Home: {geoport_folder}")
        logger.info("GeoPort folder created successfully")

    # Set permissions for the GeoPort folder
    if current_platform == 'win32':
        # Windows permissions (read/write for everyone)
        os.system(f"icacls {geoport_folder} /grant Everyone:(OI)(CI)F")
        logger.info("Permissions set for GeoPort folder on Windows")
    else:  # Linux and MacOS
        # POSIX permissions (read/write for everyone)
        os.chmod(geoport_folder, 0o777)
        logger.info("Permissions set for GeoPort folder on MacOS")



# Define the function to be executed in the thread
def run_tunnel(service_provider):

    try:
        asyncio.run(start_quic_tunnel(service_provider))

        logger.info("run_tun completed")
        sys.exit(0)

    except Exception as e:
        error_message = str(e)

        # Handle the exception, such as logging it or returning an error response
        with app.app_context():
            return jsonify({'error': error_message})

    #return

# Define a function to start the tunnel thread
def start_tunnel_thread(service_provider):
    _start_tunnel(run_tunnel, (service_provider,))


async def start_quic_tunnel(service_provider: RemoteServiceDiscoveryService) -> None:

    logger.warning("Start USB QUIC tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     logger.info("Windows System - Driver Check Required")
    #     if version_check(ios_version):
    #         logger.warning("Installing WeTest Driver - QUIC Tunnel")
    #         cli_install_wetest_drivers()

    service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    async with service.start_quic_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f"QUIC Address: {tunnel_result.address}")
        logger.info(f"QUIC Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if _tunnel_stop_requested():
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)


# Define the function to be executed in the thread
def run_tcp_tunnel(service_provider):

    try:
        asyncio.run(start_tcp_tunnel(service_provider))

        logger.info("run_tun completed")
        sys.exit(0)

    except Exception as e:
        error_message = str(e)

        # Handle the exception, such as logging it or returning an error response
        with app.app_context():
            return jsonify({'error': error_message})

    #return

# Define a function to start the tunnel thread
def start_tcp_tunnel_thread(service_provider):
    _start_tunnel(run_tcp_tunnel, (service_provider,))


async def start_tcp_tunnel(service_provider: CoreDeviceTunnelProxy) -> None:

    logger.warning("Start USB TCP tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    #service = await create_core_device_tunnel_service_using_rsd(service_provider, autopair=True)

    lockdown = create_using_usbmux(udid, autopair=True)
    #print("Lockdown for Windows: ", lockdown)
    service = CoreDeviceTunnelProxy(lockdown)
    #asyncio.run(tunnel_task(service, secrets=None, protocol=TunnelProtocol.TCP), debug=True)
    async with service.start_tcp_tunnel() as tunnel_result:
        logger.info(f"TCP Address: {tunnel_result.address}")
        logger.info(f"TCP Port: {tunnel_result.port}")
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)

        while True:
            if _tunnel_stop_requested():
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)





def is_major_version_17_or_greater(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version >= 17
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        return False

def is_major_version_less_than_16(version_string):
    # Check if the major version in the given version string is 17 or greater.
    try:
        major_version = int(version_string.split('.')[0])
        return major_version < 16
    except (ValueError, IndexError):
        # Handle invalid version string or missing major version
        logger.error(f"Error: {ValueError}, {IndexError}")
        return False


def version_check(version_string):
    try:
        # Split the version string into major and minor version parts
        version_parts = version_string.split('.')

        # Extract the major and minor version parts
        major_version = int(version_parts[0])
        minor_version = int(version_parts[1]) if len(version_parts) > 1 else 0

        # Check if the version string satisfies the condition
        if major_version == 17 and 0 <= minor_version <= 3:
            if sys.platform == 'win32':
                logger.info("Checking Windows Driver requirement")
                logger.info("Driver is required")
            return True
        else:
            if sys.platform == 'win32':
                logger.info("Driver is not required")
                return False
            logger.info("MacOS - pass")
            return False



    except (ValueError, IndexError) as e:
        logger.error(f"Driver check error: {e}")
        # Handle invalid version string or missing major/minor version
        return False

def get_user_country():
    # Device discovery and local UI must never call an Internet service.
    user_locale, _ = locale.getlocale()
    country = pycountry.countries.get(alpha_2=user_locale.split('_')[-1]) if user_locale else None
    return country.name if country else "Spain"


def get_country_from_ip():
    try:
        response = requests.get("http://ip-api.com/json/")
        if response.status_code == 200:
            data = response.json()
            country_name = data.get("country")
            if country_name:
                return country_name
            else:
                logger.warning("Failed to retrieve country name from IP geolocation service.")
        else:
            logger.error(f"Error: Unable to retrieve data. Status code: {response.status_code}")
            logger.warning("Setting to default country")
            country_name = "Spain"
        return country_name
    except Exception as e:
        logger.error(f"Error getting country from IP geolocation service: {e}")
        country_name = "Spain"
        return country_name
def get_devices_with_retry(max_attempts=10):
    if sys.platform == 'win32':
        logger.info(f"iOS Version: {ios_version}")
        if version_check(ios_version):
            logger.info("Windows Driver Install Required")
            cli_install_wetest_drivers()
    for attempt in range(1, max_attempts + 1):
        try:
            devices = asyncio.run(get_rsds(timeout))
            #dev1 = asyncio.run(get_rsds(timeout))
            #devices = asyncio.run(get_core_device_tunnel_services(timeout))
            #print("devices: ", devices)
            #print("dev1: ", dev1)
            if devices:
                return devices  # Return devices if the list is not empty
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")
        time.sleep(1)  # Add a delay between attempts if needed
    raise RuntimeError("No devices found after multiple attempts.\n Ensure you are running GeoPort as sudo / Administrator \n Please see the FAQ: https://github.com/davesc63/GeoPort/blob/main/FAQ.md \n If you still have the error please raise an issue on github: https://github.com/davesc63/GeoPort/issues ")


def get_wifi_with_retry(max_attempts=10):
    global udid, wifi_address, wifi_port

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Discovering Wifi Devices - This may take a while...")
            devices = asyncio.run(get_remote_pairing_tunnel_services(timeout))
            #devices = get_remote_pairing_tunnel_services(timeout)



            if devices:
                if udid:
                    for device in devices:
                        if device.remote_identifier == udid:
                            logger.info(f"Device found with udid: {udid}.")
                            wifi_address = device.hostname
                            wifi_port = device.port
                            return device
                else:
                    return devices
            else:
                logger.warning(f"Attempt {attempt}: No devices found")
        except Exception as e:
            logger.warning(f"Attempt {attempt}: Error occurred - {e}")

        # Add a delay between attempts
        time.sleep(1)

    raise RuntimeError("No devices found after multiple attempts. Please see the FAQ.")
@app.route('/stop_tunnel', methods=['POST'])
def stop_tunnel_thread():
    with location_service.connection_change():
        _stop_tunnels()
    return jsonify("Tunnel stopped")

@app.route('/api/data/<fuel_type>')
def get_fuel_type_data(fuel_type):
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    selected_data = next((entry for entry in all_region_data if entry['type'] == fuel_type), None)

    return jsonify(selected_data)


@app.route('/api/fuel_types')
def get_fuel_types():
    selected_fuel_region = request.args.get('region', 'All')

    if api_data is None:
        logger.error("API Data is none, sorry - Fuel data is not available")
        return jsonify({}), 500  # Return an empty response with status code 500 (Internal Server Error)

    all_region_data = next(
        (region['prices'] for region in api_data['regions'] if region['region'] == selected_fuel_region), [])

    fuel_types = set(entry['type'] for entry in all_region_data)

    return jsonify(list(fuel_types))


@app.route('/update_location', methods=['POST'])
def update_location():
    global location
    data = json_body()
    point = coordinates(data.get('lat'), data.get('lng'))
    location = f"{point['lat']} {point['lng']}"
    return 'Location updated successfully'


def check_pair_record(udid):
    global pair_record
    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")

    filename = get_remote_pairing_record_filename(udid)
    logger.info(f"Pair Record File: {filename}")

    # pair_record = get_local_pairing_record(filename, home)
    pair_record = get_preferred_pair_record(udid, home)
    #logger.info(f"Pair Record: {pair_record}")
    return pair_record

def check_developer_mode(udid, connection_type):
    try:

        logger.warning(f"Check Developer Mode")

        lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)

        result = lockdown.developer_mode_status
        logger.info(f"Developer Mode Check result:  {result}")

        # Check if developer mode is enabled
        if result:
            logger.info("Developer Mode is true")
            return True
        else:
            logger.warning("Developer Mode is false")
            return False

    except subprocess.CalledProcessError as e:
        return False


def enable_developer_mode(udid, connection_type):
    check_pair_record(udid)


    logger.info(f"Connection Type: {connection_type}")
    logger.info("Enable Developer Mode")

    home = get_home_folder()
    logger.info(f"Pair Record Home: {home}")
    #
    # filename = get_remote_pairing_record_filename(udid)
    # logger.info(f"Pair Record File: {filename}")
    #
    # pair_record = get_local_pairing_record(filename, home)
    # logger.info(f"Pair Record: {pair_record}")
    if connection_type == "Network":
        if pair_record is None:
            logger.error("Network: No Pair Record Found. Please use a USB cable first to create a pair record")
            return False, "No Pair Record Found. Please use a USB cable first to create a pair record"
    else:
        logger.error("No Pair Record Found. USB cable detected. Creating a pair record")
        pass
        #return False, "No Pair Record Found. Please use a USB cable first to create a pair record"

    lockdown = create_using_usbmux(
        udid,
        connection_type=connection_type,
        autopair=True,
        pairing_records_cache_folder=home)


    try:

        AmfiService(lockdown).enable_developer_mode()
        logger.info("Enable complete, mount developer image...")
        mount_developer_image_impl()

    except DeviceHasPasscodeSetError:
        error_message = "Error: Device has a passcode set\n \n Please temporarily remove the passcode and run GeoPort again to enable Developer Mode \n \n Go to \"Settings - Face ID & Passcode\"\n"
        logger.error(f"{error_message}")
        return False, error_message

    # except Exception as e:  # Catch any other exception
    #     logger.error(f"An error occurred: {str(e)}")
    #     return False, f"An error occurred: {str(e)}"

    return True, None




@app.route('/enable_developer_mode', methods=['POST'])
def enable_developer_mode_route():
    global udid, connection_type
    data = json_body()
    if not isinstance(data.get('udid'), str) or not data['udid'].strip():
        raise ValueError('A device identifier is required')
    selected_type = data.get('connType', connection_type)
    if selected_type not in ('USB', 'Network', 'Manual'):
        raise ValueError('Unknown device connection type')
    with location_service.connection_change():
        _stop_tunnels()
        udid, connection_type = data['udid'], selected_type
        try:
            success, reason = enable_developer_mode(udid, connection_type)
            if not success:
                raise RuntimeError(reason)
        except Exception as exc:
            raise LocationError(f'Could not enable developer mode: {exc}', 502) from exc
    return jsonify({'success': True, 'udid': udid})



def connect_device_legacy():
    global udid, connection_type, ios_version, rsd_data, rsd_host, rsd_port, wifi_address

    data = json_body()
    logger.info(f"Connect Device Data: {data}")

    # Extract the udid from the request
    udid = data.get('udid', None)
    #ios_version = data.get('ios_version')

    connection_type = data.get('connType')



    if udid in rsd_data_map:
        if connection_type in rsd_data_map[udid]:
            logger.info(f"Connect_Device Map - Looking for {udid} in {connection_type}")
            rsd_data = rsd_data_map[udid][connection_type]

            rsd_host = rsd_data['host']
            rsd_port = rsd_data['port']

            logger.info(f"RSD in udid mapping is: {rsd_data}")
            logger.info("RSD already created. Reusing connection")
            logger.info(f"RSD Data: {rsd_data}")
            return jsonify({'rsd_data': rsd_data})

        # If no matching entry found for the udid and desired connection type
        logger.info(f"No matching RSD entry found for udid: {udid} and connection type: {connection_type}")


    # Check if developer mode is enabled, and enable it if not
    #logger.info("Must be iOS17")
    if not check_developer_mode(udid, connection_type):
        # Display modal to inform the user and give options
        return jsonify({'developer_mode_required': 'True'})

    if connection_type == "USB":
        return connect_usb(data)

    elif connection_type == "Network":
        check_pair_record(udid)

        if pair_record is None:
            logger.error("No Pair Record Found. Please use a USB Cable to create one")
            return jsonify({"Error": "No Pair Record Found"})
        result = connect_wifi(data)
        #result = await connect_wifi(data)
        #return await connect_wifi(data)
        return result

    elif connection_type == "Manual":
        check_pair_record(udid)

        if pair_record is None:
            logger.error("No Pair Record Found. Please use a USB Cable to create one")
            return jsonify({"Error": "No Pair Record Found"})
        result = connect_wifi(data)
        # result = await connect_wifi(data)
        # return await connect_wifi(data)
        return result
    else:
        logger.error("Error: No matching connection type")
        return jsonify({"Error": "No matching connection type"})

def check_rsd_data():
    max_attempts = 30
    attempts = 0
    while attempts < max_attempts:
        if rsd_host is not None and rsd_port is not None:
            return True  # Data is available
        time.sleep(1)
        attempts += 1
    return False  # Data is still None after all attempts

def connect_usb(data):
    try:
        global udid, connection_type
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"USB data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.0"
        connection_type = data.get('connType')
        rsd_host = None
        rsd_port = None

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")


            logger.info(f"iOS Version: {ios_version}")
            if version_check(ios_version):
                if sys.platform == 'win32':
                    logger.warning("iOS is between 17.0 and 17.3.1, WHY?")
                    logger.warning("You should upgrade to 17.4+")
                    logger.error("We need to install a 3rd party driver for these versions")
                    logger.error("which may stop working at any time")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})
                else:
                    logger.warning("ios <17.4 on non-windows")
                    try:
                        devices = get_devices_with_retry()
                        logger.info(f"Devices: {devices}")
                        rsd = [device for device in devices if device.udid == udid]
                        if len(rsd) > 0:
                            rsd = rsd[0]
                        start_tunnel_thread(rsd)

                    except RuntimeError as e:
                        error_message = str(e)
                        logger.error(f"Error: {error_message}")
                        return jsonify({'error': 'No Devices Found'})

            else:
                global lockdown
                lockdown = create_using_usbmux(udid, autopair=True)
                logger.info(f"Create Lockdown {lockdown}")
                start_tcp_tunnel_thread(lockdown)


            #time.sleep(3)
            if not check_rsd_data():
                raise RuntimeError("Device tunnel was not established within 30 seconds")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # # Check if developer mode is enabled, and enable it if not
            # if not check_developer_mode(udid, connection_type):
            #     # Display modal to inform the user and give options
            #     return jsonify({'developer_mode_required': 'True'})

            # create LockdownServiceProvider
            #global lockdown
            lockdown = create_using_usbmux(udid, autopair=True)
            logger.info(f"Lockdown client = {lockdown}")
            #rsd_data = rsd_host, rsd_port
            rsd_host, rsd_port = rsd_data

            #rsd_data_map[udid] = rsd_data
            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")

def connect_wifi(data):
    try:
        global udid, wifi_address, connection_type, wifi_port
        global ios_version
        global rsd_data, rsd_host, rsd_port

        logger.info(f"Wifi data: {data}")

        # Extract the udid from the request
        udid = data.get('udid', None)
        ios_version = data.get('ios_version')
        #ios_version = "17.3.1"
        #wifi_address = data.get('wifiAddress')
        #logger.error(f"wifi address: {wifi_address}")
        connection_type = data.get('connType')

        if ios_version is not None and is_major_version_17_or_greater(ios_version):
            logger.info("iOS 17+ detected")

            if version_check(ios_version):
                try:
                    devices = get_wifi_with_retry()
                    #devices = "blah"
                    logger.info(f"Connect Wifi Devices: {devices}")
                    logger.info(f"Wifi Address:  {wifi_address}")
                except RuntimeError as e:
                    error_message = str(e)
                    logger.error(f"Error: {error_message}")
                    return jsonify({'error': 'No Devices Found'})


            rsd_host = None
            rsd_port = None

            # Run tun(devices) as a background task
            #asyncio.create_task(tun(devices))
            #await tun(devices)
            #start_wifi_tunnel_thread(devices)
            start_wifi_tunnel_thread()

            if not check_rsd_data():
                raise RuntimeError("Device tunnel was not established within 30 seconds")
            else:
                rsd_data = rsd_host, rsd_port
                logger.info(f"RSD Data: {rsd_data}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}
            logger.info(f"Device Connection Map: {rsd_data_map}")
            return jsonify({'rsd_data': rsd_data})

        elif ios_version is not None and not is_major_version_17_or_greater(ios_version):
            rsd_data = ios_version, udid
            logger.info(f"RSD Data: {rsd_data}")

            # create LockdownServiceProvider
            global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            #lockdown = create_using_tcp(wifi_address, udid)
            logger.info(f"Lockdown client = {lockdown}")

            rsd_data_map.setdefault(udid, {})[connection_type] = {"host": rsd_host, "port": rsd_port}

            return jsonify({'message': 'iOS version less than 17', 'rsd_data': rsd_data})

        else:
            # Invalid ios_version
            return jsonify({'error': 'No iOS version present'})
    finally:
        logger.warning("Connect Device function completed")




async def start_wifi_tcp_tunnel() -> None:

    logger.warning(f"Start Wifi TCP Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()

    #service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    lockdown = create_using_usbmux(udid)
    service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_tcp_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if _tunnel_stop_requested():
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

async def start_wifi_quic_tunnel() -> None:

    logger.warning(f"Start Wifi QUIC Tunnel")

    global terminate_tunnel_thread
    stop_remoted_if_required()
    #install_driver_if_required()

    # if sys.platform == 'win32':
    #     if is_driver_required:
    #         logger.warning("Installing WeTest Driver")
    #         cli_install_wetest_drivers()
    #get_wifi_with_retry()
    service = await create_core_device_tunnel_service_using_remotepairing(udid, wifi_address, wifi_port)
    # lockdown = create_using_usbmux(udid)
    # service = CoreDeviceTunnelProxy(lockdown)

    async with service.start_quic_tunnel() as tunnel_result:
        resume_remoted_if_required()

        logger.info(f'Identifier: {service.remote_identifier}')
        logger.info(f'Interface: {tunnel_result.interface}')
        logger.info(f'RSD Address: {tunnel_result.address}')
        logger.info(f'RSD Port: {tunnel_result.port}')
        global rsd_port
        global rsd_host
        rsd_host = tunnel_result.address

        rsd_port = str(tunnel_result.port)


        while True:
            if _tunnel_stop_requested():
                return
            # wait user input while the asyncio tasks execute
            await asyncio.sleep(.5)

# Define a function to start the tunnel thread
def start_wifi_tunnel_thread():
    _start_tunnel(run_wifi_tunnel)


def run_wifi_tunnel():
    try:
        if version_check(ios_version):
            asyncio.run(start_wifi_quic_tunnel())
        #TODO: or win32 / 17.0-17.3 special tunnel

        else:
            asyncio.run(start_wifi_tcp_tunnel())
        #await tun(devices)
    except Exception as e:
        logger.error(f"Error in run_wifi_tunnel: {e}")


@app.route('/mount_developer_image', methods=['POST'])
def mount_developer_image():
    with location_service.operation():
        if not location_service.state()['device_connection']:
            raise LocationError('Connect a device before mounting its developer image')
        try:
            mount_developer_image_impl()
        except Exception as exc:
            raise LocationError(f'Could not mount developer image: {exc}', 502) from exc
    return 'Developer image mounted successfully'


def mount_developer_image_impl():
    global lockdown
    if lockdown is None:
        lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
    auto_mount(lockdown)

@asynccontextmanager
async def device_location_session():
    """Keep DVT open between user updates, and close it only on stop/disconnect."""
    if not udid or ios_version is None:
        raise RuntimeError("No connected device")
    if is_major_version_17_or_greater(ios_version):
        entry = rsd_data_map.get(udid, {}).get(connection_type, {})
        host, port = entry.get('host'), entry.get('port')
        if not host or not port:
            raise RuntimeError("Device tunnel is not ready")
        async with RemoteServiceDiscoveryService((host, int(port))) as remote:
            with DvtSecureSocketProxyService(remote) as dvt:
                yield LocationSimulation(dvt)
    else:
        if lockdown is None:
            raise RuntimeError("Device lockdown connection is unavailable")
        auto_mount(lockdown)
        with DvtSecureSocketProxyService(lockdown=lockdown) as dvt:
            simulation = LocationSimulation(dvt)
            simulation.clear()
            yield simulation


location_service = LocationService(device_location_session)


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError('A JSON object is required')
    return data


@app.errorhandler(LocationError)
def location_error(exc):
    return jsonify({'error': str(exc), 'state': location_service.state()}), exc.status


@app.errorhandler(ValueError)
def invalid_input(exc):
    return jsonify({'error': str(exc)}), 400


@app.errorhandler(OSError)
def io_error(exc):
    return jsonify({'error': f'Local file or device operation failed: {exc}'}), 503


@app.route('/api/settings', methods=['GET', 'PUT'])
def settings_api():
    if request.method == 'PUT':
        data = json_body()
        if set(data) - {'random_radius_m', 'ui_mode'}:
            raise ValueError('Only random_radius_m and ui_mode can be changed here')
        settings_store.update(**data)
    return jsonify({**settings_store.read(), **location_service.state(),
                    'settings_warning': settings_store.warning})


@app.route('/api/base-location', methods=['PUT'])
def save_base_location():
    data = json_body()
    point = coordinates(data.get('lat'), data.get('lng'))
    return jsonify(settings_store.update(base_location=point))


@app.route('/api/location/apply', methods=['POST'])
def apply_location_api():
    data = json_body()
    mode = data.get('mode', 'base')
    if mode not in ('base', 'random'):
        raise ValueError('Location mode must be base or random')
    saved = settings_store.read()
    base = saved['base_location']
    if base is None:
        raise LocationError('Save a base coordinate first')
    point = random_offset(base, saved['random_radius_m']) if mode == 'random' else base
    location_service.apply(point)
    return jsonify({'success': True, **location_service.state()})


def _tunnel_stop_requested():
    event = getattr(threading.current_thread(), 'geoport_stop_event', None)
    return event.is_set() if event else terminate_tunnel_thread


def _stop_tunnels():
    global terminate_tunnel_thread, rsd_host, rsd_port, rsd_data, lockdown
    terminate_tunnel_thread = True
    for thread in tunnel_threads:
        thread.geoport_stop_event.set()
    for thread in tunnel_threads:
        thread.join(timeout=10)
        if thread.is_alive():
            raise LocationError('Previous device tunnel is still closing; retry after it exits')
    tunnel_threads.clear()
    rsd_data_map.clear()
    rsd_host = rsd_port = rsd_data = None
    if lockdown is not None:
        lockdown.close()
        lockdown = None


def _start_tunnel(target, arguments=()):
    global terminate_tunnel_thread
    terminate_tunnel_thread = False
    thread = threading.Thread(target=target, args=arguments, name='GeoPort-tunnel', daemon=True)
    thread.geoport_stop_event = threading.Event()
    tunnel_threads.append(thread)
    thread.start()


@app.route('/connect_device', methods=['POST'])
def connect_device():
    data = json_body()
    if not isinstance(data.get('udid'), str) or not data['udid'].strip():
        raise ValueError('A device identifier is required')
    if data.get('connType') not in ('USB', 'Network', 'Manual'):
        raise ValueError('Unknown device connection type')
    version = data.get('ios_version')
    if not isinstance(version, str) or not re.fullmatch(r'\d+(?:\.\d+){0,2}', version):
        raise ValueError('A valid iOS version is required')
    with location_service.connection_change():
        _stop_tunnels()
        try:
            response = connect_device_legacy()
            payload = response.get_json()
            if 'developer_mode_required' in payload:
                return response, 409
            if payload.get('error') or payload.get('Error'):
                return response, 502
            entry = rsd_data_map.get(data['udid'], {}).get(data['connType'], {})
            if is_major_version_17_or_greater(version):
                if not entry.get('host') or not entry.get('port'):
                    raise RuntimeError('Device tunnel is unavailable')
            elif lockdown is None:
                raise RuntimeError('Device lockdown connection is unavailable')
            location_service.connected({'udid': data['udid'], 'connType': data['connType'],
                                        'ios_version': version})
            return response
        except Exception as exc:
            _stop_tunnels()
            raise LocationError(f'Device connection failed: {exc}', 502) from exc


@app.route('/api/device/disconnect', methods=['POST'])
def disconnect_device():
    with location_service.connection_change():
        _stop_tunnels()
    return jsonify({'success': True, **location_service.state()})


def stop_set_location_thread():
    # Compatibility for the original shutdown helper.
    return location_service.stop()


@app.route('/set_location', methods=['POST'])
def set_location():
    data = json_body()
    if 'lat' in data or 'lng' in data:
        point = coordinates(data.get('lat'), data.get('lng'))
    elif location:
        point = coordinates(*location.split())
    else:
        raise ValueError("Select a coordinate first")
    location_service.apply(point)
    return 'Location set successfully'


@app.route('/stop_location', methods=['POST'])
def stop_location():
    location_service.stop()
    return 'Location cleared successfully'


def get_github_version():
    try:
        # Make a request to the GitHub API to get the content of CURRENT_VERSION file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{CURRENT_VERSION_FILE}'
        response = requests.get(url, timeout=5)

        response.raise_for_status()

        # Parse the content of the file
        github_version = response.text.strip()


        return github_version
    except requests.RequestException as e:

        return None


def get_github_broadcast():
    try:
        # Make a request to the GitHub API to get the content of CURRENT_VERSION file
        url = f'https://raw.githubusercontent.com/{GITHUB_REPO}/main/{BROADCAST_FILE}'
        logger.error(f"Github URL: {url}")

        response = requests.get(url, timeout=5)
        logger.error(f"github response: {response}")
        #response.raise_for_status()

        # Parse the content of the file
        github_broadcast = response.text.strip()
        logger.error(f"GITHUB BROADCAST MESSAGE:")

        return github_broadcast
    except requests.RequestException as e:

        return None


def remove_ansi_escape_codes(text):
    ansi_escape = re.compile(r'\x1b[^m]*m')
    return ansi_escape.sub('', text)

async def get_network_devices():
# you can also query network lockdown instances using the following:
    async for ip, lockdown in get_mobdev2_lockdowns():
        print(ip, lockdown.short_info)

@app.route('/list_devices')
def py_list_devices():
    try:
        connected_devices = {}

        # Retrieve all devices
        all_devices = list_devices()
        #wifi_devices = None
        #wifi_devices = asyncio.run(get_network_devices())
        logger.info(f"\n\nRaw Devices:  {all_devices}\n")
        #logger.info(f"\n\nWifi Devices:  {wifi_devices}\n")


        if wifihost:
            udid = args.udid
            logger.warning(f"Wifi requested to {wifihost}")
            logger.warning(f"udid: {udid}")
            lockdown = create_using_tcp(hostname=wifihost, identifier=udid)

            # udid = lockdown.udid
            # print("wifi udid", udid)
            info = lockdown.short_info
            logger.warning(f"Wifi Short Info: {info}")
            # Modify the info dictionary to include wifiConState
            wifi_connection_state = lockdown.enable_wifi_connections = True
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            info['ConnectionType'] = 'Network'

            # Substitute "Network" with "Wifi" in the connection_type
            connection_type = "Manual Wifi"
            # if connection_type == "Network":
            #     connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}






        # Iterate through all devices

        for device in all_devices:
            udid = device.serial
            connection_type = device.connection_type

            # Create lockdown and info variables
            #global lockdown
            lockdown = create_using_usbmux(udid, connection_type=connection_type, autopair=True)
            info = lockdown.short_info


            wifi_connection_state = lockdown.enable_wifi_connections

            if wifi_connection_state == False:
                logger.info("Enabling Wifi Connections")
                wifi_connection_state = lockdown.enable_wifi_connections = True
                logger.info(f"Wifi Connection State: True")

            # Modify the info dictionary to include wifiConState
            info['wifiState'] = wifi_connection_state

            # Modify the info dictionary to include user locale
            info['userLocale'] = get_user_country()

            # Substitute "Network" with "Wifi" in the connection_type
            if connection_type == "Network":
                connection_type = "Wifi"

            # If the serial already exists in the connected_devices dictionary
            if udid in connected_devices:
                # If the connection_type already exists under the serial, append the device to the list
                if connection_type in connected_devices[udid]:
                    connected_devices[udid][connection_type].append(info)
                # If the connection_type doesn't exist under the serial, create a new list with the device
                else:
                    connected_devices[udid][connection_type] = [info]
            # If the serial is new, create a new dictionary entry with the connection_type as a list
            else:
                connected_devices[udid] = {connection_type: [info]}

        logger.info(f"\n\nConnected Devices: {connected_devices}\n")

        # Check if running as sudo
        if current_platform == "darwin":
            if os.geteuid() != 0:
                logger.error("*********************** WARNING ***********************")
                logger.error("Not running as Sudo, this probably isn't going to work")
                logger.error("*********************** WARNING ***********************")
        return jsonify(connected_devices)

    except ConnectionAbortedError as e:
        logger.error(f"ConnectionAbortedError occurred: {e}")
        return {"error"}

    except Exception as e:
        error_message = str(e)
        return jsonify({'error': error_message})

def clear_geoport():
    logger.info("clear any GeoPort instances")
    substring = "GeoPort"

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name']:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()
    else:
        logger.warning("No GeoPort found")


def clear_old_geoport():
    logger.info("clear old GeoPort instances")
    substring = "GeoPort"

    current_pid = os.getpid()

    for process in psutil.process_iter(['pid', 'name']):
        if substring in process.info['name'] and process.info['pid'] != current_pid:
            logger.info(f"Found process: {process.info['pid']} - {process.info['name']}")

            # Terminate the process
            process.terminate()


def shutdown_server():
    logger.warning("shutdown server")
    location_service.stop()
    stop_set_location_thread()
    stop_tunnel_thread()
    cancel_async_tasks()
    terminate_threads()


    # Terminate the current process
    clear_geoport()

    logger.error("OS Kill")
    os.kill(os.getpid(), signal.SIGINT)
    list_threads()
    terminate_threads()
    logger.error("sys exit")
    os._exit(0)


def terminate_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        if thread != threading.main_thread():
            logger.info(f"thread: {thread}")
            terminate_flag = threading.Event()
            terminate_flag.set()
            #thread.terminate()  # Terminate the thread

def list_threads():
    """
    Terminate all threads.
    """
    for thread in threading.enumerate():
        logger.info(f"thread: {thread}")
def cancel_async_tasks():
    try:
        #loop = asyncio.get_running_loop()
        tasks = asyncio.all_tasks()
        for task in tasks:
            logger.info(f"task: {task}")
            task.cancel()
    except RuntimeError as e:
        if "no running event loop" in str(e):
            logger.error("No running event loop found.")
        else:
            raise e  # Re-raise the error if it's not related to the event loop



@app.route('/exit', methods=['POST'])
def exit_app():
    logger.warning("Exit GeoPort")
    with location_service.connection_change():
        _stop_tunnels()
    # Acknowledge first, then exit only this app process.
    def finish():
        threading.Event().wait(0.25)
        os._exit(0)
    threading.Thread(target=finish, name='GeoPort-exit', daemon=True).start()
    return jsonify({'success': True, 'message': 'GeoPort is shutting down'})


@app.route('/health')
def health():
    return jsonify({'status': 'ok'})


@app.route('/')
def index():
    mode = args.ui_mode or settings_store.read()['ui_mode']
    return redirect('/map') if mode == 'map' else render_template('lite.html')


@app.route('/lite')
def lite():
    return render_template('lite.html')


@app.route('/map')
def map_view():
    start_online_data()
    return render_template('map.html', version_message=None, github_broadcast=None,
                           user_locale=get_user_country(), app_version_num=APP_VERSION_NUMBER,
                           app_version_type=APP_VERSION_TYPE, error_message=error_message,
                           current_platform=platform, sudo_message=sudo_message)


def start_online_data():
    global online_started
    with online_lock:
        if online_started:
            return
        online_started = True
    def refresh():
        try:
            fetch_api_data(api_url)
            online_metadata['version'] = get_github_version()
            online_metadata['broadcast'] = get_github_broadcast()
        finally:
            online_metadata['complete'] = True
    threading.Thread(target=refresh, daemon=True, name='GeoPort-online').start()


@app.route('/api/online-status')
def online_status():
    start_online_data()
    return jsonify({**online_metadata, 'fuel_ready': api_data is not None})


def open_browser(port):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urlopen(f'http://127.0.0.1:{port}/health', timeout=0.3) as response:
                if response.status == 200:
                    webbrowser.open(f'http://127.0.0.1:{port}/')
                    return
        except (OSError, ValueError):
            pass
        threading.Event().wait(0.05)
    logger.error('Local server did not become ready; browser was not opened')


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0
    # with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #     try:
    #         s.bind((' ', port))
    #         return False  # Port is available
    #     except OSError:
    #         return True  # Port is already in use


# Define try_bind_listener_on_free_port function
def try_bind_listener_on_free_port():
    global chosen_port
    min_port = 49215
    max_port = 65535

    # Check if --port argument is provided
    if args.port:
        chosen_port = args.port
    else:
        chosen_port = flask_port

    if is_port_in_use(chosen_port):
        chosen_port = random.randint(min_port, max_port)
    logger.info(f'Serving: http://127.0.0.1:{chosen_port}')
    return chosen_port


if __name__ == '__main__':
    #create_geoport_folder()
    if is_windows:
        try:
            import pyi_splash

            pyi_splash.update_text('UI Loaded ...')
            logger.info("clear splash")
            pyi_splash.close()
        except:
            pass
        if not pyuac.isUserAdmin():
            print("Relaunching as Admin")
            pyuac.runAsAdmin()
            sys.exit(0)
    #else:




    chosen_port = try_bind_listener_on_free_port()

    # Check if --no-browser flag is provided
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(chosen_port,), daemon=True,
                         name='GeoPort-browser').start()
    else:
        logger.info("--no-browser flag passed")
        logger.info("Running without auto-browser popup")



    #threading.Thread(target=open_browser).start()

    app.run(debug=False, use_reloader=False, port=chosen_port, host='127.0.0.1')




