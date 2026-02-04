# MIT License
#
# Copyright (c) 2024 Contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""
Bluetooth Low Energy (BLE) Interface for Reticulum

This interface enables Reticulum communication over Bluetooth Low Energy,
allowing mesh networking between phones, computers, and IoT devices.

Configuration example:
    [[Bluetooth Mesh]]
        type = BluetoothInterface
        enabled = yes
        mode = full

        # Optional: specific device name to advertise
        # device_name = RNS-Node

        # Optional: group ID for peer authentication (same as AutoInterface)
        # group_id = reticulum

        # Optional: limit to specific adapters
        # allowed_adapters = hci0, hci1

Dependencies:
    pip install bleak          # Cross-platform BLE (scanning/central)
    pip install bless          # Cross-platform BLE (advertising/peripheral)
"""

from RNS.Interfaces.Interface import Interface
import threading
import asyncio
import time
import RNS

# Reticulum BLE Service UUIDs
# Using randomly generated UUIDs in the "custom" range
RNS_SERVICE_UUID        = "a4b30001-1234-5678-9abc-def012345678"
RNS_TX_CHARACTERISTIC   = "a4b30002-1234-5678-9abc-def012345678"  # Write to this (from central)
RNS_RX_CHARACTERISTIC   = "a4b30003-1234-5678-9abc-def012345678"  # Notify from this (to central)
RNS_ID_CHARACTERISTIC   = "a4b30004-1234-5678-9abc-def012345678"  # Group ID verification


class HDLC:
    """
    HDLC framing for packet delimiting over BLE.
    Same as used in other Reticulum interfaces.
    """
    FLAG     = 0x7E
    ESC      = 0x7D
    ESC_MASK = 0x20

    @staticmethod
    def escape(data):
        data = data.replace(bytes([HDLC.ESC]), bytes([HDLC.ESC, HDLC.ESC ^ HDLC.ESC_MASK]))
        data = data.replace(bytes([HDLC.FLAG]), bytes([HDLC.ESC, HDLC.FLAG ^ HDLC.ESC_MASK]))
        return data

    @staticmethod
    def unescape(data):
        result = bytearray()
        escape_next = False
        for byte in data:
            if escape_next:
                result.append(byte ^ HDLC.ESC_MASK)
                escape_next = False
            elif byte == HDLC.ESC:
                escape_next = True
            else:
                result.append(byte)
        return bytes(result)


class BluetoothInterface(Interface):
    """
    Main Bluetooth interface that handles:
    - BLE advertising (peripheral role)
    - BLE scanning (central role)
    - Peer discovery and management
    - Spawning per-peer interfaces
    """

    # BLE MTU is typically 247 bytes max, but negotiated
    # We use a conservative value accounting for GATT overhead
    HW_MTU = 512
    FIXED_MTU = False

    DEFAULT_IFAC_SIZE = 8
    DEFAULT_GROUP_ID = "reticulum".encode("utf-8")

    # Timing constants
    PEERING_TIMEOUT   = 30.0   # How long before a peer is considered gone
    SCAN_INTERVAL     = 5.0    # How often to scan for new peers
    ADVERTISE_INTERVAL = 2.0   # BLE advertising interval

    BITRATE_GUESS = 250000     # ~250 kbps typical BLE throughput

    def __init__(self, owner, configuration):
        # Check for required dependencies
        import importlib

        if importlib.util.find_spec('bleak') is None:
            RNS.log("BluetoothInterface requires the 'bleak' module for BLE scanning.", RNS.LOG_CRITICAL)
            RNS.log("Install it with: pip install bleak", RNS.LOG_CRITICAL)
            RNS.panic()

        if importlib.util.find_spec('bless') is None:
            RNS.log("BluetoothInterface requires the 'bless' module for BLE advertising.", RNS.LOG_CRITICAL)
            RNS.log("Install it with: pip install bless", RNS.LOG_CRITICAL)
            RNS.panic()

        super().__init__()

        # Set MTU (must be after super().__init__ which sets it to None)
        self.HW_MTU = BluetoothInterface.HW_MTU

        # Parse configuration
        c = Interface.get_config_obj(configuration)
        self.name = c["name"]
        self.owner = owner

        # Configuration options
        group_id = c["group_id"] if "group_id" in c else None
        self.device_name = c["device_name"] if "device_name" in c else "RNS-BLE"
        self.allowed_adapters = c.as_list("allowed_adapters") if "allowed_adapters" in c else None

        # Set group ID for peer authentication
        if group_id is None:
            self.group_id = BluetoothInterface.DEFAULT_GROUP_ID
        else:
            self.group_id = group_id.encode("utf-8")

        # Calculate group hash for peer verification (same as AutoInterface)
        self.group_hash = RNS.Identity.full_hash(self.group_id)

        # Interface state
        self.online = False
        self.bitrate = BluetoothInterface.BITRATE_GUESS
        self.peers = {}                    # addr -> [last_seen, BluetoothPeer]
        self.spawned_interfaces = {}       # addr -> BluetoothPeer
        self.write_lock = threading.Lock()

        # Async event loop for BLE operations
        self._loop = None
        self._loop_thread = None

        # BLE components (initialized in start())
        self._scanner = None
        self._server = None

        # Start the interface
        self._start_interface()

    def _start_interface(self):
        """Initialize and start BLE operations."""

        # Create dedicated event loop for async BLE operations
        self._loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=run_loop, daemon=True)
        self._loop_thread.start()

        # Start scanning and advertising
        asyncio.run_coroutine_threadsafe(self._start_ble(), self._loop)

        # Start peer management job
        peer_thread = threading.Thread(target=self._peer_jobs, daemon=True)
        peer_thread.start()

        RNS.log(f"{self} starting Bluetooth interface", RNS.LOG_VERBOSE)

    async def _start_ble(self):
        """Start BLE scanning and advertising."""
        try:
            from bleak import BleakScanner

            # Start continuous scanning
            self._scanner = BleakScanner(
                detection_callback=self._on_device_found,
                service_uuids=[RNS_SERVICE_UUID]
            )
            await self._scanner.start()
            RNS.log(f"{self} BLE scanner started", RNS.LOG_VERBOSE)

            # Start GATT server for advertising
            await self._start_gatt_server()

            self.online = True
            RNS.log(f"{self} Bluetooth interface online", RNS.LOG_NOTICE)

        except Exception as e:
            RNS.log(f"{self} failed to start BLE: {e}", RNS.LOG_ERROR)
            self.online = False

    async def _start_gatt_server(self):
        """Start BLE GATT server for peripheral mode."""
        try:
            from bless import BlessServer, BlessGATTCharacteristic, GATTCharacteristicProperties, GATTAttributePermissions

            self._server = BlessServer(name=self.device_name)

            # Set up request handlers
            self._server.read_request_func = self._handle_read
            self._server.write_request_func = self._handle_write

            # Add Reticulum service
            await self._server.add_new_service(RNS_SERVICE_UUID)

            # TX characteristic - centrals write to this to send us data
            # Combined read+write for better compatibility
            await self._server.add_new_characteristic(
                RNS_SERVICE_UUID,
                RNS_TX_CHARACTERISTIC,
                GATTCharacteristicProperties.read | GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
                b"",  # Empty initial value
                GATTAttributePermissions.readable | GATTAttributePermissions.writeable
            )

            # RX characteristic - we notify centrals through this
            await self._server.add_new_characteristic(
                RNS_SERVICE_UUID,
                RNS_RX_CHARACTERISTIC,
                GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
                b"",  # Empty initial value
                GATTAttributePermissions.readable
            )

            # ID characteristic - for group verification
            await self._server.add_new_characteristic(
                RNS_SERVICE_UUID,
                RNS_ID_CHARACTERISTIC,
                GATTCharacteristicProperties.read,
                self.group_hash[:16],  # First 16 bytes of group hash
                GATTAttributePermissions.readable
            )

            # Start advertising
            await self._server.start()
            RNS.log(f"{self} GATT server started, advertising as '{self.device_name}'", RNS.LOG_VERBOSE)

        except Exception as e:
            RNS.log(f"{self} failed to start GATT server: {e}", RNS.LOG_ERROR)

    def _handle_read(self, characteristic, **kwargs):
        """Handle read request from a connected central."""
        RNS.log(f"{self} read request for {characteristic.uuid}", RNS.LOG_DEBUG)
        return characteristic.value

    def _handle_write(self, characteristic, value, **kwargs):
        """Handle incoming write from a connected central."""
        RNS.log(f"{self} write received: {len(value)} bytes", RNS.LOG_DEBUG)
        if characteristic.uuid.lower() == RNS_TX_CHARACTERISTIC.lower():
            # Process incoming data from peer
            self._process_raw_incoming(value, None)

    def _on_device_found(self, device, advertisement_data):
        """Callback when BLE scanner finds a device."""
        # Check if device is advertising Reticulum service
        if RNS_SERVICE_UUID.lower() in [s.lower() for s in advertisement_data.service_uuids]:
            addr = device.address

            if addr not in self.peers:
                RNS.log(f"{self} discovered peer: {device.name} ({addr})", RNS.LOG_DEBUG)

                # Connect to peer asynchronously
                asyncio.run_coroutine_threadsafe(
                    self._connect_to_peer(device),
                    self._loop
                )

    async def _connect_to_peer(self, device):
        """Connect to a discovered peer and verify group membership."""
        try:
            from bleak import BleakClient

            async with BleakClient(device.address) as client:
                # Read group ID characteristic to verify peer
                group_data = await client.read_gatt_char(RNS_ID_CHARACTERISTIC)

                # Verify group hash matches
                if group_data == self.group_hash[:16]:
                    self._add_peer(device.address, client)
                else:
                    RNS.log(f"{self} peer {device.address} has different group ID, ignoring", RNS.LOG_DEBUG)

        except Exception as e:
            RNS.log(f"{self} failed to connect to peer {device.address}: {e}", RNS.LOG_DEBUG)

    def _add_peer(self, addr, client=None):
        """Add a verified peer."""
        if addr not in self.spawned_interfaces:
            # Create spawned interface for this peer
            peer_interface = BluetoothPeer(self, addr)
            peer_interface.OUT = self.OUT
            peer_interface.IN = self.IN
            peer_interface.parent_interface = self
            peer_interface.bitrate = self.bitrate
            peer_interface.HW_MTU = self.HW_MTU
            peer_interface.online = True

            self.spawned_interfaces[addr] = peer_interface
            self.peers[addr] = [time.time(), peer_interface]

            RNS.Transport.interfaces.append(peer_interface)
            RNS.log(f"{self} added peer {addr}", RNS.LOG_DEBUG)
        else:
            # Refresh existing peer
            self.peers[addr][0] = time.time()

    def _peer_jobs(self):
        """Background thread for peer management."""
        while True:
            time.sleep(self.SCAN_INTERVAL)

            if not self.online:
                continue

            now = time.time()
            timed_out = []

            # Check for timed out peers
            for addr, peer_data in list(self.peers.items()):
                last_seen = peer_data[0]
                if now > last_seen + self.PEERING_TIMEOUT:
                    timed_out.append(addr)

            # Remove timed out peers
            for addr in timed_out:
                if addr in self.spawned_interfaces:
                    peer = self.spawned_interfaces.pop(addr)
                    peer.teardown()
                if addr in self.peers:
                    self.peers.pop(addr)
                RNS.log(f"{self} peer {addr} timed out", RNS.LOG_DEBUG)

    def _process_raw_incoming(self, data, addr):
        """Process raw incoming BLE data (may be fragmented)."""
        # TODO: Implement HDLC reassembly for fragmented packets
        # For now, assume complete packets
        if addr and addr in self.spawned_interfaces:
            self.spawned_interfaces[addr].process_incoming(data)
        else:
            # Broadcast to owner if we can't determine peer
            self.rxb += len(data)
            self.owner.inbound(data, self)

    def process_outgoing(self, data):
        """Send data to all connected peers (broadcast)."""
        if not self.online:
            return

        # Frame data with HDLC
        framed = bytes([HDLC.FLAG]) + HDLC.escape(data) + bytes([HDLC.FLAG])

        for addr, peer in list(self.spawned_interfaces.items()):
            if peer.online:
                peer.process_outgoing(framed)

    def detach(self):
        """Detach and stop the interface."""
        self.online = False

        if self._loop:
            asyncio.run_coroutine_threadsafe(self._stop_ble(), self._loop)

    async def _stop_ble(self):
        """Stop BLE operations."""
        if self._scanner:
            await self._scanner.stop()
        if self._server:
            await self._server.stop()

    def __str__(self):
        return f"BluetoothInterface[{self.name}]"


class BluetoothPeer(Interface):
    """
    Represents a single Bluetooth peer connection.
    Spawned by BluetoothInterface for each discovered peer.
    """

    DEFAULT_IFAC_SIZE = 8

    def __init__(self, owner, addr):
        super().__init__()
        self.owner = owner
        self.parent_interface = owner
        self.addr = addr
        self.name = f"BLE:{addr[-8:]}"  # Short name from MAC
        self.online = False
        self.HW_MTU = owner.HW_MTU

        # BLE client for this peer
        self._client = None
        self._connected = False

        # Receive buffer for HDLC reassembly
        self._rx_buffer = bytearray()
        self._in_frame = False
        self._escape = False

    def process_incoming(self, data):
        """Process incoming data from this peer."""
        if not self.online:
            return

        # HDLC frame reassembly
        for byte in data:
            if self._in_frame and byte == HDLC.FLAG:
                # End of frame
                self._in_frame = False
                if len(self._rx_buffer) > 0:
                    packet = HDLC.unescape(bytes(self._rx_buffer))
                    self.rxb += len(packet)
                    self.owner.rxb += len(packet)
                    self.owner.owner.inbound(packet, self)
                self._rx_buffer = bytearray()

            elif byte == HDLC.FLAG:
                # Start of frame
                self._in_frame = True
                self._rx_buffer = bytearray()

            elif self._in_frame and len(self._rx_buffer) < self.HW_MTU:
                self._rx_buffer.append(byte)

    def process_outgoing(self, data):
        """Send data to this peer."""
        if not self.online:
            return

        # Queue async write operation
        asyncio.run_coroutine_threadsafe(
            self._write_to_peer(data),
            self.owner._loop
        )

    async def _write_to_peer(self, data):
        """Async write to peer's TX characteristic."""
        try:
            from bleak import BleakClient

            if not self._connected:
                self._client = BleakClient(self.addr)
                await self._client.connect()
                self._connected = True

            # BLE characteristic writes may need chunking
            # Max ATT payload is typically 512 bytes after MTU negotiation
            chunk_size = 512
            for i in range(0, len(data), chunk_size):
                chunk = data[i:i + chunk_size]
                await self._client.write_gatt_char(RNS_TX_CHARACTERISTIC, chunk)

            self.txb += len(data)
            self.owner.txb += len(data)

        except Exception as e:
            RNS.log(f"{self} write failed: {e}", RNS.LOG_DEBUG)
            self._connected = False
            self.online = False

    def detach(self):
        """Detach this peer interface."""
        self.online = False

    def teardown(self):
        """Clean up peer connection."""
        self.online = False
        self.OUT = False
        self.IN = False

        if self._client and self._connected:
            asyncio.run_coroutine_threadsafe(
                self._client.disconnect(),
                self.owner._loop
            )

        if self in RNS.Transport.interfaces:
            RNS.Transport.interfaces.remove(self)

        RNS.log(f"{self} torn down", RNS.LOG_DEBUG)

    def __str__(self):
        return f"BluetoothPeer[{self.addr}]"


# Register interface class for Reticulum
interface_class = BluetoothInterface
