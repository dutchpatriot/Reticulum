#!/usr/bin/env python3
"""
Simple GATT server test with proper characteristic setup.
"""

import asyncio
import sys

async def main():
    from bless import BlessServer, BlessGATTCharacteristic
    from bless import GATTCharacteristicProperties, GATTAttributePermissions

    print("Starting simple GATT server...")

    # Trigger for logging
    def read_request(characteristic, **kwargs):
        print(f"[READ] {characteristic.uuid}")
        return characteristic.value

    def write_request(characteristic, value, **kwargs):
        print(f"[WRITE] {characteristic.uuid} = {value.hex()}")
        characteristic.value = value

    server = BlessServer(name="RNS-Test")
    server.read_request_func = read_request
    server.write_request_func = write_request

    service_uuid = "a4b30001-1234-5678-9abc-def012345678"

    await server.add_new_service(service_uuid)

    # Characteristic with READ + WRITE properties
    char_uuid = "a4b30002-1234-5678-9abc-def012345678"

    await server.add_new_characteristic(
        service_uuid,
        char_uuid,
        GATTCharacteristicProperties.read | GATTCharacteristicProperties.write | GATTCharacteristicProperties.write_without_response,
        b"Hello from RNS!",
        GATTAttributePermissions.readable | GATTAttributePermissions.writeable
    )

    # ID characteristic - read only
    id_uuid = "a4b30004-1234-5678-9abc-def012345678"
    await server.add_new_characteristic(
        service_uuid,
        id_uuid,
        GATTCharacteristicProperties.read,
        b"RNS-GROUP-ID-XX",  # 16 bytes
        GATTAttributePermissions.readable
    )

    print(f"Service UUID: {service_uuid}")
    print(f"Char UUID:    {char_uuid} (read+write)")
    print(f"ID UUID:      {id_uuid} (read)")

    await server.start()
    print("\nGATT server running! Connect with nRF Connect...")
    print("Press Ctrl+C to stop\n")

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    await server.stop()
    print("Server stopped.")

if __name__ == "__main__":
    asyncio.run(main())
