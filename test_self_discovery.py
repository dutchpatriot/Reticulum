#!/usr/bin/env python3
"""
Test self-discovery: Start GATT server and scan for it.
This verifies our BLE advertising is working correctly.
"""

import asyncio
import threading
import time

# Our UUIDs
RNS_SERVICE_UUID = "a4b30001-1234-5678-9abc-def012345678"

async def run_server():
    """Run GATT server that advertises our service."""
    from bless import BlessServer
    from bless import GATTCharacteristicProperties, GATTAttributePermissions

    print("[SERVER] Starting GATT server...")

    server = BlessServer(name="RNS-Test-Node")

    # Add our service
    await server.add_new_service(RNS_SERVICE_UUID)

    # Add a simple characteristic
    await server.add_new_characteristic(
        RNS_SERVICE_UUID,
        "a4b30002-1234-5678-9abc-def012345678",
        GATTCharacteristicProperties.read,
        b"Hello RNS",
        GATTAttributePermissions.readable
    )

    await server.start()
    print("[SERVER] GATT server started, advertising...")
    print(f"[SERVER] Service UUID: {RNS_SERVICE_UUID}")

    # Run for a while
    await asyncio.sleep(15)

    await server.stop()
    print("[SERVER] GATT server stopped")


async def run_scanner():
    """Scan for our GATT server."""
    from bleak import BleakScanner

    print("[SCANNER] Starting BLE scanner...")

    found_self = False

    def on_device(device, adv_data):
        nonlocal found_self
        service_uuids = [s.lower() for s in adv_data.service_uuids]

        if RNS_SERVICE_UUID.lower() in service_uuids:
            print(f"\n[SCANNER] *** FOUND RNS NODE! ***")
            print(f"[SCANNER]   Name: {device.name}")
            print(f"[SCANNER]   Address: {device.address}")
            print(f"[SCANNER]   RSSI: {adv_data.rssi} dBm")
            found_self = True

    scanner = BleakScanner(detection_callback=on_device)
    await scanner.start()

    # Scan for a while
    for i in range(12):
        await asyncio.sleep(1)
        if found_self:
            print("[SCANNER] Self-discovery successful!")
            break
        if i % 3 == 0:
            print(f"[SCANNER] Scanning... ({i}s)")

    await scanner.stop()
    print("[SCANNER] Scanner stopped")

    return found_self


async def main():
    print("=" * 60)
    print("Self-Discovery Test")
    print("=" * 60)
    print()
    print("This test starts a GATT server and tries to discover it.")
    print("Note: Self-discovery may not work on all Bluetooth adapters.")
    print()

    # Run both concurrently
    server_task = asyncio.create_task(run_server())

    # Give server time to start
    await asyncio.sleep(2)

    scanner_task = asyncio.create_task(run_scanner())

    # Wait for both
    await asyncio.gather(server_task, scanner_task)

    print()
    print("=" * 60)
    print("Test complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
