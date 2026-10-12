"""Pinned pymobiledevice3 TCP adapter with one owner for the macOS TUN fd."""
import asyncio
from contextlib import asynccontextmanager
import sys
from pymobiledevice3.remote.common import TunnelProtocol
from pymobiledevice3.remote.tunnel_service import (
    CoreDeviceTunnelProxy as BaseProxy, RemotePairingTcpTunnel, TunnelResult, LOOPBACK_HEADER)


class OwnedFdTcpTunnel(RemotePairingTcpTunnel):
    async def tun_read_task(self):
        if sys.platform != 'darwin':
            return await super().tun_read_task()
        # aiofiles.open(fd) in 4.4.0 owns and closes the same descriptor as the
        # TUN socket. Read via the event loop so cancellation never closes it.
        loop = asyncio.get_running_loop()
        fd = self.tun.fileno()
        size = self.tun.mtu + len(LOOPBACK_HEADER)
        while True:
            ready = loop.create_future()
            def readable():
                if not ready.done():
                    ready.set_result(None)
            loop.add_reader(fd, readable)
            try:
                await ready
            finally:
                loop.remove_reader(fd)
            packet = self.tun.read(size)
            if not packet.startswith(LOOPBACK_HEADER):
                raise RuntimeError('Invalid TUN packet header')
            await self.send_packet_to_device(packet[len(LOOPBACK_HEADER):])


class CoreDeviceTunnelProxy(BaseProxy):
    @asynccontextmanager
    async def start_tcp_tunnel(self):
        self._service = await self._lockdown.aio_start_lockdown_service(self.SERVICE_NAME)
        tunnel = OwnedFdTcpTunnel(self._service.reader, self._service.writer)
        parameters = await tunnel.request_tunnel_establish()
        tunnel.start_tunnel(parameters['clientParameters']['address'], parameters['clientParameters']['mtu'])
        try:
            yield TunnelResult(tunnel.tun.name, parameters['serverAddress'],
                               parameters['serverRSDPort'], TunnelProtocol.TCP, tunnel)
        finally:
            await tunnel.stop_tunnel()
