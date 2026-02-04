#!/usr/bin/env python3
"""
Test Reticulum with BluetoothInterface

This script starts Reticulum with the Bluetooth interface enabled
and monitors for peer discovery.
"""

import sys
import time
import argparse

# Ensure our local RNS is used
sys.path.insert(0, '/home/marco/Software/BlueWebMess/Reticulum')

import RNS

def setup_bluetooth_interface():
    """Configure and return a Reticulum instance with Bluetooth."""

    # Create a minimal config for testing
    # We'll manually instantiate the interface

    print("Starting Reticulum...")
    reticulum = RNS.Reticulum(configdir=None, loglevel=RNS.LOG_VERBOSE)

    print("Creating BluetoothInterface...")
    from RNS.Interfaces.BluetoothInterface import BluetoothInterface

    # Configuration for the interface
    config = {
        "name": "Bluetooth Test",
        "device_name": "RNS-Test-Node",
        "group_id": "test-mesh",
    }

    try:
        bt_interface = BluetoothInterface(RNS.Transport, config)
        bt_interface.OUT = True
        bt_interface.IN = True

        # Register with transport
        RNS.Transport.interfaces.append(bt_interface)

        print(f"BluetoothInterface created: {bt_interface}")
        print(f"  Online: {bt_interface.online}")
        print(f"  Bitrate: {bt_interface.bitrate}")
        print(f"  HW_MTU: {bt_interface.HW_MTU}")

        return reticulum, bt_interface

    except Exception as e:
        print(f"Failed to create BluetoothInterface: {e}")
        import traceback
        traceback.print_exc()
        return reticulum, None


def main():
    parser = argparse.ArgumentParser(description='Test Reticulum Bluetooth Interface')
    parser.add_argument('--duration', type=int, default=30,
                        help='How long to run the test (seconds)')
    args = parser.parse_args()

    print("=" * 60)
    print("Reticulum Bluetooth Interface Test")
    print("=" * 60)

    reticulum, bt_interface = setup_bluetooth_interface()

    if bt_interface is None:
        print("Failed to start Bluetooth interface")
        return 1

    print(f"\nRunning for {args.duration} seconds...")
    print("Watching for peer discovery...\n")

    try:
        start_time = time.time()
        last_peer_count = 0

        while time.time() - start_time < args.duration:
            # Check for new peers
            current_peers = len(bt_interface.peers)
            if current_peers != last_peer_count:
                print(f"[{time.time() - start_time:.1f}s] Peer count: {current_peers}")
                for addr, peer_data in bt_interface.peers.items():
                    print(f"  - {addr}")
                last_peer_count = current_peers

            # Show stats every 10 seconds
            elapsed = int(time.time() - start_time)
            if elapsed > 0 and elapsed % 10 == 0:
                print(f"[{elapsed}s] Stats: RX={bt_interface.rxb} bytes, TX={bt_interface.txb} bytes, Peers={current_peers}")

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nInterrupted by user")

    finally:
        print("\nShutting down...")
        bt_interface.detach()

    print("\nFinal stats:")
    print(f"  RX: {bt_interface.rxb} bytes")
    print(f"  TX: {bt_interface.txb} bytes")
    print(f"  Peers discovered: {len(bt_interface.peers)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
