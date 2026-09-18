from pathlib import Path

path = Path("scripts/realtime_live_call_smoke.py")
text = path.read_text()
old = "_direct_usb_target(devices_output, serial)"
if old not in text:
    raise RuntimeError("expected remaining live target helper call was not found")
path.write_text(text.replace(old, "is_direct_usb_target(devices_output, serial)"))
