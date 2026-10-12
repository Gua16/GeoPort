import asyncio
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from device_tunnel import OwnedFdTcpTunnel, LOOPBACK_HEADER


class FdTests(unittest.IsolatedAsyncioTestCase):
    async def test_packet_forwarding_and_cancel_do_not_close_tun_descriptor(self):
        read, write = os.pipe()
        packets = []
        async def send(packet):
            packets.append(packet)
        fake = SimpleNamespace(tun=SimpleNamespace(fileno=lambda:read,mtu=1500,read=lambda n:os.read(read,n)),
                               send_packet_to_device=send)
        try:
            with patch('device_tunnel.sys.platform','darwin'):
                task=asyncio.create_task(OwnedFdTcpTunnel.tun_read_task(fake))
                await asyncio.sleep(0)
                os.write(write,LOOPBACK_HEADER+b'packet')
                for _ in range(10):
                    if packets:break
                    await asyncio.sleep(.01)
                self.assertEqual(packets,[b'packet'])
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
                os.fstat(read)  # The actual TUN owner must still be able to close it.
        finally:
            os.close(read);os.close(write)
