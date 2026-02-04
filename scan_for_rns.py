#!/usr/bin/env python3
"""
Scan for Reticulum BLE nodes.
Run this on a second device to discover nodes.
"""

import asyncio
import sys

# Reticulum BLE Service UUID
RNS_SERVICE_UUID = "a4b30001-1234-5678-9abc-def012345678"

async def scan():
    from bleak import BleakScanner

    print("Scanning for Reticulum BLE nodes...")
    print(f"Looking for service: {RNS_SERVICE_UUID}")
    print("-" * 50)

    def detection_callback(device, advertisement_data):
        # Check if this device is advertising our service
        service_uuids = [s.lower() for s in advertisement_data.service_uuids]

        if RNS_SERVICE_UUID.lower() in service_uuids:
            print(f"\n*** FOUND RNS NODE! ***")
            print(f"  Name: {device.name}")
            print(f"  Address: {device.address}")
            print(f"  RSSI: {advertisement_data.rssi} dBm")
            print(f"  Services: {advertisement_data.service_uuids}")
        else:
            # Show other devices too (but less prominently)
            name = device.name or "(unnamed)"
            print(f"  [{advertisement_data.rssi:4d} dBm] {name}: {device.address}")

    scanner = BleakScanner(detection_callback=detection_callback)

    await scanner.start()
    print("\nScanning... (press Ctrl+C to stop)\n")

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await scanner.stop()

if __name__ == "__main__":
    try:
        asyncio.run(scan())
    except KeyboardInterrupt:
        print("\nScan stopped.")
