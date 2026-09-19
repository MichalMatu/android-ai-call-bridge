from pathlib import Path

root = Path.cwd()
probe = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalPhoneLlmLiveCallProbe.kt"
activity = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
runner = root / "scripts/local_phone_llm_live_call.py"
test = root / "scripts/test_local_phone_llm_live_call.py"

probe.write_text(r'''package pl.michalmatu.aicallbridge

import android.content.Context
import android.media.AudioManager
import android.os.Handler
import android.os.Looper
import pl.michalmatu.aicallbridge.agent.CallCommitmentGate
import pl.michalmatu.aicallbridge.agent.CallConfirmationPolicy
import pl.michalmatu.aicallbridge.agent.CallConstraints
import pl.michalmatu.aicallbridge.agent.CallPreferences
import pl.michalmatu.aicallbridge.agent.CallResolvedTarget
import pl.michalmatu.aicallbridge.agent.CallTask
import pl.michalmatu.aicallbridge.agent.CallWorkflow
import pl.michalmatu.aicallbridge.localspeech.LocalSpeechFormat
import pl.michalmatu.aicallbridge.localspeech.LocalSpeechTextPipeline
import pl.michalmatu.aicallbridge.session.CallMediaEndpointLease
import pl.michalmatu.aicallbridge.session.CallMediaSessionRuntime
import pl.michalmatu.aicallbridge.session.CallMediaSessionSnapshot
import pl.michalmatu.aicallbridge.session.CallMediaSessionState
import pl.michalmatu.aicallbridge.textagent.CallTextAgentOutputApprovalPolicy
import pl.michalmatu.aicallbridge.textagent.LocalPhoneLlmBackendFactory
import java.io.File
import java.time.Instant
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean
import java.util.function.Consumer

/** One bounded live cellular turn: telephony RX -> local STT -> phone LLM -> approval -> TTS -> TX. */
internal object LocalPhoneLlmLiveCallProbe {
    private const val REPORT_FILE = "local-phone-llm-live-call-report.txt"
    private const val INPUT_CAPTURE_MS = 5_000
    private const val TIMEOUT_MS = 45_000L

    fun run(context: Context, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val audioManager = appContext.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
        if (audioManager == null || audioManager.mode != AudioManager.MODE_IN_CALL) {
            callback(immediateReport("cellular_call_not_active"))
            return
        }
        Run(appContext, callback).start()
    }

    private class Run(
        private val context: Context,
        private val callback: (String) -> Unit,
    ) {
        private val handler = Handler(Looper.getMainLooper())
        private val finished = AtomicBoolean(false)
        private val mediaTurnStarted = AtomicBoolean(false)
        private val executor: ExecutorService = Executors.newSingleThreadExecutor { runnable ->
            Thread(runnable, "LocalPhoneLlmLiveTurn").apply { isDaemon = true }
        }
        private val lines = mutableListOf(
            "probe=local_phone_llm_live_call",
            "call_required=true",
            "backend_location=phone_loopback",
            "approval_policy=application_owned",
            "timestamp_utc=${Instant.now()}",
            "target_pcm=mono,pcm16,${LocalSpeechFormat.SAMPLE_RATE_HZ}",
        )
        private val backend = LocalPhoneLlmBackendFactory.create()
        private val workflow = activeWorkflow()
        private val pipeline = LocalSpeechTextPipeline(
            context,
            backend,
            CallTextAgentOutputApprovalPolicy(
                workflow,
                CallCommitmentGate { "live-local-phone-llm-token" },
            ),
        )
        private var mediaRuntime: CallMediaSessionRuntime? = null
        private var activeLease: CallMediaEndpointLease? = null
        private var turnStartedAtMs: Long = 0L

        private val timeout = Runnable { finish(false, "probe_timeout") }

        fun start() {
            try {
                mediaRuntime = CallMediaSessionRuntime(
                    context,
                    Consumer { snapshot -> onMediaSnapshot(snapshot) },
                )
                handler.postDelayed(timeout, TIMEOUT_MS)
                val generation = mediaRuntime!!.coordinator().start(LocalSpeechFormat.SAMPLE_RATE_HZ)
                lines += "media_generation=$generation"
            } catch (error: Throwable) {
                finish(false, "media_launch_${error.javaClass.simpleName}")
            }
        }

        private fun onMediaSnapshot(snapshot: CallMediaSessionSnapshot) {
            if (finished.get()) return
            when (snapshot.state) {
                CallMediaSessionState.ACTIVE -> {
                    if (mediaTurnStarted.compareAndSet(false, true)) {
                        context.mainExecutor.execute { beginTurn(snapshot.generation) }
                    }
                }
                CallMediaSessionState.FAILED -> {
                    context.mainExecutor.execute {
                        finish(false, "media_${snapshot.failure.name.lowercase()}")
                    }
                }
                else -> Unit
            }
        }

        private fun beginTurn(generation: Long) {
            if (finished.get()) return
            val lease = try {
                mediaRuntime?.coordinator()?.activeEndpointLease(generation)
                    ?: throw IllegalStateException("media_runtime_unavailable")
            } catch (error: Throwable) {
                finish(false, "endpoint_${error.javaClass.simpleName}")
                return
            }
            activeLease = lease
            lines += "media_active=true"
            turnStartedAtMs = android.os.SystemClock.elapsedRealtime()
            pipeline.start(object : LocalSpeechTextPipeline.Listener {
                override fun onSpeechInputReady() {
                    lines += "stt_ready=true"
                    executor.execute { captureInputTurn(lease) }
                }

                override fun onUserTranscript(text: String) {
                    lines += "stt_text=${sanitize(text)}"
                    lines += "stt_transcript_nonblank=${text.isNotBlank()}"
                    lines += "stt_elapsed_ms=${elapsedTurnMs()}"
                }

                override fun onApprovedText(text: String) {
                    lines += "backend_complete_response=true"
                    lines += "approved_text=${sanitize(text)}"
                    lines += "approved_text_nonblank=${text.isNotBlank()}"
                    lines += "llm_approved_elapsed_ms=${elapsedTurnMs()}"
                }

                override fun onOutputPcm16Mono16k(pcm: ByteArray) {
                    lines += "output_tts_pcm_bytes=${pcm.size}"
                    executor.execute { writeOutputTurn(lease, pcm) }
                }

                override fun onDroppedText() = finish(false, "output_dropped")
                override fun onError(reason: String) = finish(false, reason)
            })
        }

        private fun captureInputTurn(lease: CallMediaEndpointLease) {
            val targetBytes = LocalSpeechFormat.SAMPLE_RATE_HZ * 2 * INPUT_CAPTURE_MS / 1_000
            val buffer = ByteArray(LocalSpeechFormat.bytesForDurationMs(100))
            var total = 0
            try {
                while (total < targetBytes && !finished.get()) {
                    val read = lease.downlink().read(buffer, 0, minOf(buffer.size, targetBytes - total))
                    if (read < 0) break
                    if (read == 0) continue
                    if (!pipeline.writeInputPcm(buffer, 0, read)) {
                        throw IllegalStateException("stt_pcm_write_failed")
                    }
                    total += read
                }
                lines += "telephony_rx_pcm_bytes=$total"
                if (total < LocalSpeechFormat.bytesForDurationMs(500)) {
                    context.mainExecutor.execute { finish(false, "telephony_rx_too_short") }
                    return
                }
                pipeline.finishInput()
                lines += "stt_pcm_eof_sent=true"
            } catch (error: Throwable) {
                context.mainExecutor.execute {
                    finish(false, "telephony_rx_${error.javaClass.simpleName}")
                }
            }
        }

        private fun writeOutputTurn(lease: CallMediaEndpointLease, pcm: ByteArray) {
            try {
                if (pcm.isEmpty()) throw IllegalStateException("tts_pcm_empty")
                lease.uplink().write(pcm)
                lease.uplink().flush()
                lines += "telephony_tx_pcm_bytes=${pcm.size}"
                lines += "turn_complete_elapsed_ms=${elapsedTurnMs()}"
                context.mainExecutor.execute { finish(true) }
            } catch (error: Throwable) {
                context.mainExecutor.execute {
                    finish(false, "telephony_tx_${error.javaClass.simpleName}")
                }
            }
        }

        private fun elapsedTurnMs(): Long =
            (android.os.SystemClock.elapsedRealtime() - turnStartedAtMs).coerceAtLeast(0L)

        private fun finish(success: Boolean, reason: String? = null) {
            if (!finished.compareAndSet(false, true)) return
            handler.removeCallbacks(timeout)
            try { pipeline.close() } catch (_: Throwable) {}
            activeLease = null
            try { mediaRuntime?.coordinator()?.takeOverNow() } catch (_: Throwable) {}
            try { mediaRuntime?.close() } catch (_: Throwable) {}
            mediaRuntime = null
            executor.shutdownNow()
            lines += "local_phone_llm_live_call_success=$success"
            if (reason != null) lines += "failure_reason=${sanitize(reason)}"
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            try { File(context.filesDir, REPORT_FILE).writeText(report) } catch (_: Throwable) {}
            context.mainExecutor.execute { callback(report) }
        }
    }

    private fun activeWorkflow(): CallWorkflow {
        val task = CallTask(
            "Orange test call",
            "conduct one non-committing test turn",
            "customer service",
            CallConstraints.unconstrained(),
            CallPreferences.none(),
            emptyMap(),
        )
        val workflow = CallWorkflow(task, CallConfirmationPolicy()) { }
        workflow.resolveTarget(CallResolvedTarget("Orange support", "allowlisted"))
        workflow.markDialing()
        workflow.markCallActive()
        return workflow
    }

    private fun immediateReport(reason: String): String =
        "probe=local_phone_llm_live_call\n" +
            "local_phone_llm_live_call_success=false\n" +
            "failure_reason=$reason\n" +
            "probe_complete=true\n"

    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').replace('=', ':').take(240)
}
''')

s = activity.read_text()
case_anchor = '''        when {\n            intent.getBooleanExtra(EXTRA_RUN_REALTIME_LIVE_CALL_SMOKE, false) -> {\n'''
case_block = '''        when {\n            intent.getBooleanExtra(EXTRA_RUN_LOCAL_PHONE_LLM_LIVE_CALL_PROBE, false) -> {\n                statusView.text = "Running local phone LLM live-call probe…"\n                Log.i(TAG, "local_phone_llm_live_call_probe_start=true")\n                LocalPhoneLlmLiveCallProbe.run(this) { result ->\n                    runOnUiThread {\n                        statusView.text = result\n                        Log.i(TAG, "local_phone_llm_live_call_probe_result:\\n$result")\n                        finish()\n                    }\n                }\n            }\n            intent.getBooleanExtra(EXTRA_RUN_REALTIME_LIVE_CALL_SMOKE, false) -> {\n'''
if 'EXTRA_RUN_LOCAL_PHONE_LLM_LIVE_CALL_PROBE' not in s:
    if s.count(case_anchor) != 1:
        raise RuntimeError("diagnostic when anchor mismatch")
    s = s.replace(case_anchor, case_block, 1)
const_anchor = '        const val EXTRA_RUN_REALTIME_LIVE_CALL_SMOKE = "run_realtime_live_call_smoke"\n'
const_line = '        const val EXTRA_RUN_LOCAL_PHONE_LLM_LIVE_CALL_PROBE = "run_local_phone_llm_live_call_probe"\n'
if const_line not in s:
    if s.count(const_anchor) != 1:
        raise RuntimeError("diagnostic constant anchor mismatch")
    s = s.replace(const_anchor, const_line + const_anchor, 1)
activity.write_text(s)

runner.write_text(r'''#!/usr/bin/env python3
"""One bounded allowlisted cellular call using the local S22 STT -> LLM -> TTS pipeline."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from autonomous_call_loop import wait_for_active_call, wait_for_audio_signal, wait_for_idle
from realtime_live_call_smoke import validate_live_preflight
from realtime_network_smoke import PACKAGE_NAME, PROBE_ACTIVITY, is_direct_usb_target
from s22_call_control import Adb, normalize_number

ORANGE_SUPPORT_NUMBER = "510100100"
ALLOWLIST = frozenset({ORANGE_SUPPORT_NUMBER})
DEFAULT_SERIAL = "RFCT70L7E8J"
LLM_PORT = 18115
REPORT_PATH = "files/local-phone-llm-live-call-report.txt"
PROBE_TIMEOUT_SECONDS = 55.0


def normalize_allowlisted_target(raw: str) -> str:
    number = normalize_number(raw)
    if number not in ALLOWLIST:
        raise ValueError("target is not in the operator-defined live-test allowlist")
    return number


def build_probe_start_args(serial: str) -> list[str]:
    return [
        "adb", "-s", serial, "shell", "am", "start", "-W", "-n", PROBE_ACTIVITY,
        "--ez", "run_local_phone_llm_live_call_probe", "true",
    ]


def parse_probe_report(text: str) -> Optional[dict[str, str]]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    if values.get("probe_complete") != "true":
        return None
    return values


def _devices_output() -> str:
    return subprocess.run(
        ["adb", "devices", "-l"], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout


def _wait_bluetooth(adb: Adb, expected: str, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = adb.shell(["settings", "get", "global", "bluetooth_on"], check=False).strip()
        if value == expected:
            return
        time.sleep(0.25)
    raise RuntimeError(f"Bluetooth did not reach expected state {expected}")


def _set_bluetooth(adb: Adb, enabled: bool) -> None:
    action = "enable" if enabled else "disable"
    output = adb.shell(["cmd", "bluetooth_manager", action], check=False)
    if "Unknown command" in output or "not found" in output:
        raise RuntimeError(f"could not {action} Bluetooth through shell")
    _wait_bluetooth(adb, "1" if enabled else "0")


def _health_check(serial: str) -> None:
    subprocess.run(["adb", "-s", serial, "forward", "--remove", f"tcp:{LLM_PORT}"], check=False)
    subprocess.run(["adb", "-s", serial, "forward", f"tcp:{LLM_PORT}", f"tcp:{LLM_PORT}"], check=True)
    with urllib.request.urlopen(f"http://127.0.0.1:{LLM_PORT}/health", timeout=3) as response:
        body = response.read().decode("utf-8", errors="replace")
    if '"status":"ok"' not in body.replace(" ", ""):
        raise RuntimeError("local phone LLM health check failed")


def _read_report(adb: Adb) -> str:
    return adb.shell(["run-as", PACKAGE_NAME, "cat", REPORT_PATH], check=False).replace("\r", "")


def _remove_report(adb: Adb) -> None:
    adb.shell(["run-as", PACKAGE_NAME, "rm", "-f", REPORT_PATH], check=False)


def _wait_report(adb: Adb, timeout: float = PROBE_TIMEOUT_SECONDS) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if adb.call_state() != 2:
            raise RuntimeError("cellular call ended before local live probe completed")
        text = _read_report(adb)
        parsed = parse_probe_report(text)
        if parsed is not None:
            print("--- local phone live report ---")
            print(text, end="" if text.endswith("\n") else "\n")
            print("--- end local phone live report ---")
            return parsed
        time.sleep(0.25)
    raise TimeoutError("local phone live probe did not produce a terminal report")


def _require_preflight(adb: Adb) -> None:
    devices = _devices_output()
    if not is_direct_usb_target(devices, adb.serial or ""):
        raise RuntimeError("local phone live call requires exact direct USB S22 target")
    bluetooth = adb.shell(["settings", "get", "global", "bluetooth_on"]).strip()
    call_state = adb.call_state()
    audio_dump = adb.shell(["dumpsys", "audio"])
    snapshot = validate_live_preflight(
        serial=adb.serial or "",
        devices_output=devices,
        bluetooth_setting=bluetooth,
        call_state=call_state if call_state is not None else -1,
        audio_dump=audio_dump,
    )
    print(
        "live_preflight=true," +
        f"mode:{snapshot.audio_mode},device:{snapshot.active_device_type},muted:{snapshot.voice_call_muted}"
    )


def run_orange_support_once(serial: str = DEFAULT_SERIAL) -> dict[str, str]:
    number = normalize_allowlisted_target(ORANGE_SUPPORT_NUMBER)
    adb = Adb(serial)
    if not is_direct_usb_target(_devices_output(), serial):
        raise RuntimeError("target S22 is not connected through exact direct USB ADB")
    if adb.call_state() != 0:
        raise RuntimeError("refusing to dial because cellular call state is not IDLE")
    _health_check(serial)

    original_bt = adb.shell(["settings", "get", "global", "bluetooth_on"], check=False).strip()
    if original_bt not in {"0", "1"}:
        raise RuntimeError("could not determine Bluetooth state")
    changed_bt = False
    dialed = False
    muted = False
    started_at = time.monotonic()
    try:
        if original_bt == "1":
            _set_bluetooth(adb, False)
            changed_bt = True
            print("bluetooth_disabled_for_test=true")

        print(f"allowlisted_target={number}")
        adb.dial(number)
        dialed = True
        print("dial_requested=true")
        wait_for_active_call(adb, 30.0)

        adb.shell(["cmd", "audio", "adj-mute", "0"])
        muted = True
        time.sleep(0.3)
        _require_preflight(adb)

        signal = wait_for_audio_signal(adb, timeout_seconds=25.0)
        print(f"orange_downlink_signal=true,rms:{signal.rms:.3f},peak:{signal.peak}")

        if time.monotonic() - started_at > 60.0:
            raise TimeoutError("bounded call budget exhausted before AI turn")

        _remove_report(adb)
        adb.shell(["am", "force-stop", PACKAGE_NAME], check=False)
        subprocess.run(build_probe_start_args(serial), check=True)
        report = _wait_report(adb)
        if report.get("local_phone_llm_live_call_success") != "true":
            raise RuntimeError("local phone live probe reported failure: " + report.get("failure_reason", "unknown"))
        if report.get("stt_transcript_nonblank") != "true":
            raise RuntimeError("live STT transcript was blank")
        if report.get("approved_text_nonblank") != "true":
            raise RuntimeError("live LLM response was blank or not approved")
        if int(report.get("telephony_tx_pcm_bytes", "0")) <= 0:
            raise RuntimeError("live TTS produced no telephony TX bytes")
        print("local_phone_llm_orange_live_turn_proven_s22=true")
        return report
    finally:
        adb.shell(["am", "force-stop", PACKAGE_NAME], check=False)
        if dialed and adb.call_state() != 0:
            adb.hangup()
            print("hangup_requested=true")
            print(f"idle_after_hangup={wait_for_idle(adb, 10.0)}")
        if muted:
            adb.shell(["cmd", "audio", "adj-unmute", "0"], check=False)
            print("voice_call_unmute_cleanup_requested=true")
        if changed_bt:
            try:
                _set_bluetooth(adb, True)
                print("bluetooth_restored=true")
            except Exception as error:
                print(f"bluetooth_restore_error={error}", file=sys.stderr)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) > 1:
        print("usage: local_phone_llm_live_call.py [adb-serial]", file=sys.stderr)
        return 2
    serial = args[0] if args else DEFAULT_SERIAL
    try:
        run_orange_support_once(serial)
        return 0
    except (ValueError, RuntimeError, TimeoutError, subprocess.CalledProcessError) as error:
        print(f"local phone live call failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
''')
runner.chmod(0o755)

# Keep the RED test's report input as real newlines rather than literal backslash-n.
s = test.read_text()
s = s.replace('"stt_text=witaj\\\\napproved_text=dzień dobry\\\\n"', '"stt_text=witaj\\napproved_text=dzień dobry\\n"')
s = s.replace('"local_phone_llm_live_call_success=true\\\\nprobe_complete=true\\\\n"', '"local_phone_llm_live_call_success=true\\nprobe_complete=true\\n"')
test.write_text(s)
print("local_phone_live_green_patch_applied=true")
