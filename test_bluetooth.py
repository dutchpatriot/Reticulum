#!/usr/bin/env python3
"""
Quick test script for BluetoothInterface
"""

import sys
import time
import asyncio

print("=" * 60)
print("Bluetooth Interface Test")
print("=" * 60)

# Test 1: Can we import bleak?
print("\n[1] Testing bleak import...")
try:
    import bleak
    from importlib.metadata import version
    print(f"    ✓ bleak version: {version('bleak')}")
except ImportError as e:
    print(f"    ✗ Failed: {e}")
    sys.exit(1)

# Test 2: Can we import bless?
print("\n[2] Testing bless import...")
try:
    import bless
    print(f"    ✓ bless imported")
except ImportError as e:
    print(f"    ✗ Failed: {e}")
    sys.exit(1)

# Test 3: Can we scan for BLE devices?
print("\n[3] Scanning for BLE devices (5 seconds)...")
async def scan_test():
    from bleak import BleakScanner
    devices = await BleakScanner.discover(timeout=5.0)
    return devices

try:
    devices = asyncio.run(scan_test())
    print(f"    ✓ Found {len(devices)} BLE devices:")
    for d in devices[:10]:  # Show first 10
        name = d.name or "(unnamed)"
        print(f"      - {name}: {d.address}")
    if len(devices) > 10:
        print(f"      ... and {len(devices) - 10} more")
except Exception as e:
    print(f"    ✗ Scan failed: {e}")

# Test 4: Can we import our BluetoothInterface?
print("\n[4] Testing BluetoothInterface import...")
try:
    sys.path.insert(0, '/home/marco/Software/BlueWebMess/Reticulum')
    from RNS.Interfaces.BluetoothInterface import BluetoothInterface, BluetoothPeer, HDLC
    print("    ✓ BluetoothInterface imported successfully")
except Exception as e:
    print(f"    ✗ Failed: {e}")
    import traceback
    traceback.print_exc()

# Test 5: Test HDLC framing
print("\n[5] Testing HDLC framing...")
try:
    test_data = b"Hello Reticulum!"
    escaped = HDLC.escape(test_data)
    framed = bytes([HDLC.FLAG]) + escaped + bytes([HDLC.FLAG])
    print(f"    Original: {test_data}")
    print(f"    Framed:   {framed.hex()}")

    # Test with special characters
    special_data = bytes([0x7E, 0x7D, 0x00, 0xFF])  # Contains FLAG and ESC
    escaped_special = HDLC.escape(special_data)
    unescaped = HDLC.unescape(escaped_special)
    assert unescaped == special_data, "HDLC roundtrip failed!"
    print(f"    ✓ HDLC escape/unescape roundtrip OK")
except Exception as e:
    print(f"    ✗ Failed: {e}")

# Test 6: Try to start GATT server
print("\n[6] Testing GATT server startup...")
async def gatt_test():
    from bless import BlessServer
    server = BlessServer(name="RNS-Test")

    # Try to add service
    await server.add_new_service("a4b30001-1234-5678-9abc-def012345678")
    print("    ✓ GATT service created")

    # Try to start (this actually advertises)
    await server.start()
    print("    ✓ GATT server started, advertising...")

    # Keep alive for a few seconds
    await asyncio.sleep(3)

    await server.stop()
    print("    ✓ GATT server stopped")

try:
    asyncio.run(gatt_test())
except Exception as e:
    print(f"    ✗ GATT server failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test complete!")
print("=" * 60)
