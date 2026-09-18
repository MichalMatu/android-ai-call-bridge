from pathlib import Path

path = Path("scripts/realtime_live_call_smoke.py")
text = path.read_text()
if "isis_direct_usb_target" not in text:
    raise RuntimeError("expected migration typo was not found")
path.write_text(text.replace("isis_direct_usb_target", "is_direct_usb_target"))
