#!/usr/bin/env python3
import importlib.util
import sys


def load_v1(path: str):
    spec = importlib.util.spec_from_file_location("local_mac_backend_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load v1 helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_green(v1):
    v1.BACKEND.parent.mkdir(parents=True, exist_ok=True)
    v1.BACKEND.write_text(v1.BACKEND_TEXT, encoding="utf-8")
    v1.PROBE.parent.mkdir(parents=True, exist_ok=True)
    v1.PROBE.write_text(v1.PROBE_TEXT, encoding="utf-8")
    v1.DEBUG_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    v1.DEBUG_MANIFEST.write_text(v1.DEBUG_MANIFEST_TEXT, encoding="utf-8")

    activity = v1.ACTIVITY.read_text(encoding="utf-8")
    signature = "    private fun runRequestedProbe() {\n"
    block = '''    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_MAC_TEXT_BACKEND_PROBE, false)) {\n            val baseUrl = intent.getStringExtra(EXTRA_LOCAL_TEXT_BASE_URL).orEmpty()\n            val model = intent.getStringExtra(EXTRA_LOCAL_TEXT_MODEL).orEmpty()\n            if (baseUrl.isBlank() || model.isBlank()) {\n                finishWithError("local_text_backend_config_missing")\n                return\n            }\n            statusView.text = "Running local Mac text backend probe…"\n            Log.i(TAG, "local_mac_text_backend_probe_start=true")\n            LocalMacTextBackendProbe.run(this, baseUrl, model) { result ->\n                runOnUiThread {\n                    statusView.text = result\n                    Log.i(TAG, "local_mac_text_backend_probe_result:\\n$result")\n                    finish()\n                }\n            }\n            return\n        }\n\n'''
    if activity.count(signature) != 1:
        raise RuntimeError(f"activity runRequestedProbe signature expected once, got {activity.count(signature)}")
    activity = activity.replace(signature, block, 1)

    const_anchor = '''        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n'''
    const_block = '''        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n        const val EXTRA_RUN_LOCAL_MAC_TEXT_BACKEND_PROBE = "run_local_mac_text_backend_probe"\n        const val EXTRA_LOCAL_TEXT_BASE_URL = "local_text_base_url"\n        const val EXTRA_LOCAL_TEXT_MODEL = "local_text_model"\n        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n'''
    if activity.count(const_anchor) != 1:
        raise RuntimeError(f"activity constant anchor expected once, got {activity.count(const_anchor)}")
    v1.ACTIVITY.write_text(activity.replace(const_anchor, const_block, 1), encoding="utf-8")
    print("local_mac_text_backend_green_written=true")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] != "green":
        raise SystemExit("usage: local-mac-openai-compatible-backend-v2.py <v1-helper> green")
    write_green(load_v1(sys.argv[1]))
