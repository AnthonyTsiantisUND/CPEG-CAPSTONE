import asyncio
from bleak import BleakScanner, BleakClient

async def main():
    print("🔍 Scanning for BLE devices... (5 seconds)")
    devices = await BleakScanner.discover(timeout=5.0)

    if not devices:
        print("No BLE devices found!")
        return

    print("\n📡 Found devices:")
    for i, d in enumerate(devices):
        print(f"{i}: {d.name}   [{d.address}]")

    print("\nEnter the number of the device you want to connect to:")
    idx = int(input("> ").strip())

    if idx < 0 or idx >= len(devices):
        print("Invalid selection!")
        return

    device = devices[idx]
    print(f"\n🔗 Attempting connection to: {device.name} [{device.address}]...\n")

    try:
        async with BleakClient(device.address) as client:
            if client.is_connected:
                print(f"✅ Successfully connected to {device.name}!")
            else:
                print("❌ Connection failed.")
    except Exception as e:
        print(f"\n❗ ERROR during connection:\n{e}")

asyncio.run(main())
