from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise RuntimeError(f"missing patch anchor in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


# Quick Tunnel parsing must not accept a valid host as a prefix of an attacker host.
replace_once(
    "scripts/realtime_offcall_lab.py",
    r'    r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com\b",',
    r'    r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com(?![A-Za-z0-9.-])",',
)

# Child processes get a small allowlisted environment instead of inheriting unrelated host secrets.
replace_once(
    "scripts/realtime_offcall_lab.py",
    "PopenFactory = Callable[..., subprocess.Popen]\n",
    "_BASE_CHILD_ENV_KEYS = (\n"
    "    \"PATH\", \"HOME\", \"TMPDIR\", \"LANG\", \"LC_ALL\",\n"
    "    \"SSL_CERT_FILE\", \"SSL_CERT_DIR\", \"ANDROID_HOME\",\n"
    "    \"ANDROID_SDK_ROOT\", \"ADB_VENDOR_KEYS\",\n"
    ")\n\n"
    "PopenFactory = Callable[..., subprocess.Popen]\n",
)
replace_once(
    "scripts/realtime_offcall_lab.py",
    "def build_broker_environment(\n",
    "def _base_child_environment(host_env: Mapping[str, str]) -> dict[str, str]:\n"
    "    return {\n"
    "        key: value\n"
    "        for key in _BASE_CHILD_ENV_KEYS\n"
    "        if (value := host_env.get(key)) is not None and value != \"\"\n"
    "    }\n\n\n"
    "def build_broker_environment(\n",
)
replace_once(
    "scripts/realtime_offcall_lab.py",
    "    child = dict(host_env)\n"
    "    child[\"OPENAI_API_KEY\"] = api_key\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_TOKEN\"] = broker_token\n"
    "    child.pop(\"AI_CALL_BRIDGE_BROKER_HTTPS_URL\", None)\n"
    "    return child\n",
    "    child = _base_child_environment(host_env)\n"
    "    child[\"OPENAI_API_KEY\"] = api_key\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_TOKEN\"] = broker_token\n"
    "    for optional_key in (\"OPENAI_REALTIME_MODEL\", \"OPENAI_SAFETY_IDENTIFIER\"):\n"
    "        optional_value = host_env.get(optional_key)\n"
    "        if optional_value:\n"
    "            child[optional_key] = optional_value\n"
    "    return child\n",
)
replace_once(
    "scripts/realtime_offcall_lab.py",
    "def build_tunnel_environment(host_env: Mapping[str, str]) -> dict[str, str]:\n"
    "    child = dict(host_env)\n"
    "    child.pop(\"OPENAI_API_KEY\", None)\n"
    "    child.pop(\"AI_CALL_BRIDGE_BROKER_TOKEN\", None)\n"
    "    child.pop(\"AI_CALL_BRIDGE_BROKER_HTTPS_URL\", None)\n"
    "    return child\n",
    "def build_tunnel_environment(host_env: Mapping[str, str]) -> dict[str, str]:\n"
    "    return _base_child_environment(host_env)\n",
)
replace_once(
    "scripts/realtime_offcall_lab.py",
    "    child = dict(host_env)\n"
    "    child.pop(\"OPENAI_API_KEY\", None)\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_TOKEN\"] = broker_token\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_HTTPS_URL\"] = credential_endpoint\n"
    "    return child\n",
    "    child = _base_child_environment(host_env)\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_TOKEN\"] = broker_token\n"
    "    child[\"AI_CALL_BRIDGE_BROKER_HTTPS_URL\"] = credential_endpoint\n"
    "    return child\n",
)

replace_once(
    "scripts/test_realtime_offcall_lab.py",
    "    def test_tunnel_parser_accepts_only_https_trycloudflare_host(self):\n",
    "    def test_child_environments_do_not_forward_unrelated_host_secrets(self):\n"
    "        from realtime_offcall_lab import (\n"
    "            build_broker_environment, build_smoke_environment, build_tunnel_environment\n"
    "        )\n"
    "        host = {\n"
    "            \"PATH\": \"/bin\", \"HOME\": \"/tmp/home\",\n"
    "            \"OPENAI_API_KEY\": \"sk-host-secret\",\n"
    "            \"OPENAI_REALTIME_MODEL\": \"gpt-realtime-2.1\",\n"
    "            \"GITHUB_TOKEN\": \"must-not-leak\",\n"
    "            \"AWS_SECRET_ACCESS_KEY\": \"must-not-leak\",\n"
    "        }\n"
    "        token = \"broker-\" + \"x\" * 40\n"
    "        endpoint = \"https://quiet-moon.trycloudflare.com/v1/realtime/client-secret\"\n"
    "        children = (\n"
    "            build_broker_environment(host, api_key=host[\"OPENAI_API_KEY\"], broker_token=token),\n"
    "            build_tunnel_environment(host),\n"
    "            build_smoke_environment(host, broker_token=token, credential_endpoint=endpoint),\n"
    "        )\n"
    "        for child in children:\n"
    "            self.assertNotIn(\"GITHUB_TOKEN\", child)\n"
    "            self.assertNotIn(\"AWS_SECRET_ACCESS_KEY\", child)\n"
    "        self.assertEqual(\"gpt-realtime-2.1\", children[0][\"OPENAI_REALTIME_MODEL\"])\n"
    "        self.assertNotIn(\"OPENAI_REALTIME_MODEL\", children[1])\n"
    "        self.assertNotIn(\"OPENAI_REALTIME_MODEL\", children[2])\n\n"
    "    def test_tunnel_parser_accepts_only_https_trycloudflare_host(self):\n",
)
replace_once(
    "scripts/test_realtime_offcall_lab.py",
    "        self.assertIsNone(parse_quick_tunnel_url(\"https://trycloudflare.com.evil.test\"))\n",
    "        self.assertIsNone(parse_quick_tunnel_url(\"https://trycloudflare.com.evil.test\"))\n"
    "        self.assertIsNone(\n"
    "            parse_quick_tunnel_url(\"https://quiet-moon.trycloudflare.com.evil.test\")\n"
    "        )\n",
)

# Share exact direct-USB target validation between off-call and live-call smoke paths.
replace_once(
    "scripts/realtime_network_smoke.py",
    "CALL_STATE_RE = re.compile(r\"mCallState=(\\d+)\")\n",
    "CALL_STATE_RE = re.compile(r\"mCallState=(\\d+)\")\nTARGET_ADB_MODEL = \"SM_S906B\"\n",
)
replace_once(
    "scripts/realtime_network_smoke.py",
    "def _adb_text(runner: ByteRunner, serial: str, *shell_args: str) -> str:\n",
    "def is_direct_usb_target(devices_output: str, serial: str) -> bool:\n"
    "    for raw_line in devices_output.splitlines():\n"
    "        parts = raw_line.split()\n"
    "        if not parts or parts[0] != serial:\n"
    "            continue\n"
    "        if len(parts) < 2 or parts[1] != \"device\":\n"
    "            return False\n"
    "        has_usb_transport = any(part.startswith(\"usb:\") for part in parts[2:])\n"
    "        has_target_model = f\"model:{TARGET_ADB_MODEL}\" in parts[2:]\n"
    "        return has_usb_transport and has_target_model\n"
    "    return False\n\n\n"
    "def _adb_text(runner: ByteRunner, serial: str, *shell_args: str) -> str:\n",
)
replace_once(
    "scripts/realtime_network_smoke.py",
    "    executor = runner or SubprocessRunner()\n"
    "    if _call_state(executor, serial) != 0:\n",
    "    executor = runner or SubprocessRunner()\n"
    "    devices_output = executor.run_bytes([\"adb\", \"devices\", \"-l\"]).decode(\n"
    "        \"utf-8\", errors=\"replace\"\n"
    "    )\n"
    "    if not is_direct_usb_target(devices_output, serial):\n"
    "        raise RuntimeError(\"Realtime network smoke requires direct USB ADB to the target S22+\")\n"
    "    if _call_state(executor, serial) != 0:\n",
)

replace_once(
    "scripts/realtime_live_call_smoke.py",
    "    SmokeEnvironment,\n    SubprocessRunner,\n    stage_private_config,\n",
    "    SmokeEnvironment,\n    SubprocessRunner,\n    is_direct_usb_target,\n    stage_private_config,\n",
)
replace_once("scripts/realtime_live_call_smoke.py", "TARGET_ADB_MODEL = \"SM_S906B\"\n", "")
live = Path("scripts/realtime_live_call_smoke.py")
text = live.read_text()
start = text.find("def _direct_usb_target(devices_output: str, serial: str) -> bool:\n")
end = text.find("\n\ndef _voice_call_muted", start)
if start < 0 or end < 0:
    raise RuntimeError("missing live target helper boundary")
text = text[:start] + text[end + 2:]
text = text.replace(
    "direct_usb = _direct_usb_target(devices_output, serial)",
    "direct_usb = is_direct_usb_target(devices_output, serial)",
    1,
)
live.write_text(text)

replace_once(
    "scripts/test_realtime_network_smoke.py",
    "    parse_probe_result,\n    stage_private_config,\n",
    "    is_direct_usb_target,\n    parse_probe_result,\n    run_smoke,\n    stage_private_config,\n",
)
replace_once(
    "scripts/test_realtime_network_smoke.py",
    "class RealtimeNetworkSmokeTest(unittest.TestCase):\n",
    "class RealtimeNetworkSmokeTest(unittest.TestCase):\n"
    "    def test_direct_usb_target_requires_exact_target_shape(self):\n"
    "        devices = (\"List of devices attached\\n\"\n"
    "            \"RFCT70L7E8J device usb:18874368X product:g0sxeea model:SM_S906B transport_id:3\\n\")\n"
    "        self.assertTrue(is_direct_usb_target(devices, \"RFCT70L7E8J\"))\n"
    "        self.assertFalse(is_direct_usb_target(devices.replace(\"usb:18874368X \", \"\"), \"RFCT70L7E8J\"))\n"
    "        self.assertFalse(is_direct_usb_target(devices.replace(\"model:SM_S906B\", \"model:OTHER\"), \"RFCT70L7E8J\"))\n"
    "        self.assertFalse(is_direct_usb_target(devices, \"OTHER_SERIAL\"))\n\n"
    "    def test_wrong_target_refuses_before_secret_staging(self):\n"
    "        runner = RefusalRunner(b\"RFCT70L7E8J device product:g0sxeea model:SM_S906B transport_id:3\\n\")\n"
    "        env = SmokeEnvironment.from_mapping({\n"
    "            \"AI_CALL_BRIDGE_BROKER_HTTPS_URL\": \"https://broker.example.test/v1/realtime/client-secret\",\n"
    "            \"AI_CALL_BRIDGE_BROKER_TOKEN\": \"broker-token-\" + \"x\" * 24,\n"
    "        })\n"
    "        with self.assertRaisesRegex(RuntimeError, \"direct USB\"):\n"
    "            run_smoke(\"RFCT70L7E8J\", env, runner=runner)\n"
    "        joined = [\" \".join(call.args) for call in runner.calls]\n"
    "        self.assertEqual(\"adb devices -l\", joined[0])\n"
    "        self.assertFalse(any(\"cat > files/realtime-network-smoke.json\" in call for call in joined))\n"
    "        self.assertFalse(any(env.broker_token in call for call in joined))\n\n",
)
replace_once(
    "scripts/test_realtime_network_smoke.py",
    "class RecordingRunner:\n",
    "class RefusalRunner:\n"
    "    def __init__(self, devices_output: bytes):\n"
    "        self.devices_output = devices_output\n"
    "        self.calls: list[RecordedCall] = []\n\n"
    "    def run_bytes(self, args, *, input_bytes=b\"\", check=True):\n"
    "        args = list(args)\n"
    "        self.calls.append(RecordedCall(args, bytes(input_bytes)))\n"
    "        if args == [\"adb\", \"devices\", \"-l\"]:\n"
    "            return self.devices_output\n"
    "        raise AssertionError(f\"unexpected command after target refusal: {args}\")\n\n\n"
    "class RecordingRunner:\n",
)
