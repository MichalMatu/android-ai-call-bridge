from pathlib import Path
import sys

ROOT = Path.cwd()

TEST = '''package pl.michalmatu.aicallbridge.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CallRuntimeModeTest {
    @Test
    fun defaultsPreferLocalSpeechWithTextApiBrain() {
        val selection = CallRuntimeSelection()

        assertEquals(CallAudioMode.LOCAL_STT_TTS, selection.audioMode)
        assertEquals(TextLlmProvider.OPENAI_TEXT, selection.textLlmProvider)
        assertTrue(selection.audioMode.usesTextLlm)
    }

    @Test
    fun storedValuesRoundTripAndUnknownValuesFailSafeToDefaults() {
        assertEquals(CallAudioMode.OPENAI_REALTIME_AUDIO, CallAudioMode.fromStored("OPENAI_REALTIME_AUDIO"))
        assertEquals(TextLlmProvider.LOCAL_MAC_LLM, TextLlmProvider.fromStored("LOCAL_MAC_LLM"))
        assertEquals(CallAudioMode.LOCAL_STT_TTS, CallAudioMode.fromStored("unknown"))
        assertEquals(TextLlmProvider.OPENAI_TEXT, TextLlmProvider.fromStored(null))
    }

    @Test
    fun realtimeAudioDoesNotUseTextLlmButKeepsProviderAsIndependentPreference() {
        val selection = CallRuntimeSelection(
            audioMode = CallAudioMode.OPENAI_REALTIME_AUDIO,
            textLlmProvider = TextLlmProvider.LOCAL_MAC_LLM,
        )

        assertFalse(selection.audioMode.usesTextLlm)
        assertEquals(TextLlmProvider.LOCAL_MAC_LLM, selection.textLlmProvider)
    }
}
'''

MODE = '''package pl.michalmatu.aicallbridge.runtime

enum class CallAudioMode(
    val displayName: String,
    val usesTextLlm: Boolean,
) {
    LOCAL_STT_TTS("Local STT + TTS (S22)", true),
    OPENAI_REALTIME_AUDIO("OpenAI Realtime Audio (frozen)", false),
    ;

    companion object {
        fun fromStored(value: String?): CallAudioMode =
            entries.firstOrNull { it.name == value } ?: LOCAL_STT_TTS
    }
}

enum class TextLlmProvider(val displayName: String) {
    OPENAI_TEXT("OpenAI API (text)"),
    LOCAL_MAC_LLM("Local LLM server (Mac)"),
    ;

    companion object {
        fun fromStored(value: String?): TextLlmProvider =
            entries.firstOrNull { it.name == value } ?: OPENAI_TEXT
    }
}

data class CallRuntimeSelection(
    val audioMode: CallAudioMode = CallAudioMode.LOCAL_STT_TTS,
    val textLlmProvider: TextLlmProvider = TextLlmProvider.OPENAI_TEXT,
)
'''

PREFS = '''package pl.michalmatu.aicallbridge.runtime

import android.content.Context

class CallRuntimePreferences(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun load(): CallRuntimeSelection = CallRuntimeSelection(
        audioMode = CallAudioMode.fromStored(preferences.getString(KEY_AUDIO_MODE, null)),
        textLlmProvider = TextLlmProvider.fromStored(preferences.getString(KEY_TEXT_LLM_PROVIDER, null)),
    )

    fun saveAudioMode(mode: CallAudioMode) {
        preferences.edit().putString(KEY_AUDIO_MODE, mode.name).apply()
    }

    fun saveTextLlmProvider(provider: TextLlmProvider) {
        preferences.edit().putString(KEY_TEXT_LLM_PROVIDER, provider.name).apply()
    }

    private companion object {
        const val PREFERENCES_NAME = "call_runtime_preferences"
        const val KEY_AUDIO_MODE = "audio_mode"
        const val KEY_TEXT_LLM_PROVIDER = "text_llm_provider"
    }
}
'''

MAIN = '''package pl.michalmatu.aicallbridge

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Bundle
import android.util.Log
import android.view.ViewGroup
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import pl.michalmatu.aicallbridge.runtime.CallAudioMode
import pl.michalmatu.aicallbridge.runtime.CallRuntimePreferences
import pl.michalmatu.aicallbridge.runtime.TextLlmProvider
import pl.michalmatu.aicallbridge.shizuku.ShizukuUserServiceProbe
import rikka.shizuku.Shizuku

class MainActivity : Activity() {
    private lateinit var statusView: TextView
    private lateinit var runtimePreferences: CallRuntimePreferences
    private lateinit var selectedAudioMode: CallAudioMode
    private lateinit var selectedTextLlmProvider: TextLlmProvider
    private lateinit var textLlmProviderSpinner: Spinner
    private var pendingShizukuProbe = false
    private var pendingShizukuLiveProbe = false

    private val shizukuBinderReceivedListener = Shizuku.OnBinderReceivedListener {
        if (pendingShizukuProbe) {
            runShizukuProbe(pendingShizukuLiveProbe)
        }
    }

    private val shizukuPermissionResultListener = Shizuku.OnRequestPermissionResultListener {
            requestCode,
            grantResult,
        ->
        if (requestCode != REQUEST_SHIZUKU) {
            return@OnRequestPermissionResultListener
        }

        if (grantResult == PackageManager.PERMISSION_GRANTED) {
            runShizukuProbe(pendingShizukuLiveProbe)
        } else {
            pendingShizukuProbe = false
            pendingShizukuLiveProbe = false
            statusView.text = "Shizuku permission denied"
            Log.i(TAG, "shizuku_probe_permission=denied")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        runtimePreferences = CallRuntimePreferences(this)
        val initialSelection = runtimePreferences.load()
        selectedAudioMode = initialSelection.audioMode
        selectedTextLlmProvider = initialSelection.textLlmProvider

        statusView = TextView(this).apply {
            text = runtimeSelectionSummary()
            textSize = 15f
            setTextIsSelectable(true)
        }

        val audioModeSpinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                CallAudioMode.entries.map { it.displayName },
            )
            setSelection(CallAudioMode.entries.indexOf(selectedAudioMode))
        }

        textLlmProviderSpinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                TextLlmProvider.entries.map { it.displayName },
            )
            setSelection(TextLlmProvider.entries.indexOf(selectedTextLlmProvider))
            isEnabled = selectedAudioMode.usesTextLlm
        }

        audioModeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: android.view.View?, position: Int, id: Long) {
                selectedAudioMode = CallAudioMode.entries[position]
                runtimePreferences.saveAudioMode(selectedAudioMode)
                textLlmProviderSpinner.isEnabled = selectedAudioMode.usesTextLlm
                statusView.text = runtimeSelectionSummary()
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        textLlmProviderSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: android.view.View?, position: Int, id: Long) {
                selectedTextLlmProvider = TextLlmProvider.entries[position]
                runtimePreferences.saveTextLlmProvider(selectedTextLlmProvider)
                statusView.text = runtimeSelectionSummary()
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        val requestMicButton = Button(this).apply {
            text = "Grant microphone permission"
            setOnClickListener { requestMicrophonePermissionIfNeeded() }
        }

        val capabilityProbeButton = Button(this).apply {
            text = "Run device capability probe"
            setOnClickListener { runCapabilityProbe() }
        }

        val shizukuProbeButton = Button(this).apply {
            text = "Run Shizuku UserService probe"
            setOnClickListener { runShizukuProbe(false) }
        }

        val probeCaptureButton = Button(this).apply {
            text = "Probe call downlink capture"
            setOnClickListener {
                statusView.text = "Downlink backend is under Phase 2 validation."
            }
        }

        val probeInjectionButton = Button(this).apply {
            text = "Probe call uplink injection"
            setOnClickListener {
                statusView.text = "Uplink backend is under Phase 2 validation."
            }
        }

        val takeoverButton = Button(this).apply {
            text = "TAKE OVER / STOP AI AUDIO"
            isAllCaps = true
            setOnClickListener {
                statusView.text = "Takeover requested. Active transport cleanup is handled fail-safe."
            }
        }

        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
            addView(TextView(this@MainActivity).apply {
                text = "Android AI Call Bridge"
                textSize = 24f
            })
            addView(TextView(this@MainActivity).apply { text = "Audio mode" })
            addView(audioModeSpinner)
            addView(TextView(this@MainActivity).apply { text = "LLM provider (text mode)" })
            addView(textLlmProviderSpinner)
            addView(requestMicButton)
            addView(capabilityProbeButton)
            addView(shizukuProbeButton)
            addView(probeCaptureButton)
            addView(probeInjectionButton)
            addView(takeoverButton)
            addView(
                statusView,
                LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                ).apply { topMargin = 24 },
            )
        }

        setContentView(
            ScrollView(this).apply {
                addView(
                    content,
                    ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                    ),
                )
            },
        )

        Shizuku.addBinderReceivedListenerSticky(shizukuBinderReceivedListener)
        Shizuku.addRequestPermissionResultListener(shizukuPermissionResultListener)

        if (intent.getBooleanExtra(EXTRA_RUN_CAPABILITY_PROBE, false)) {
            runCapabilityProbe()
        }
    }

    override fun onDestroy() {
        Shizuku.removeBinderReceivedListener(shizukuBinderReceivedListener)
        Shizuku.removeRequestPermissionResultListener(shizukuPermissionResultListener)
        super.onDestroy()
    }

    private fun runtimeSelectionSummary(): String = buildString {
        append("Audio mode: ").append(selectedAudioMode.displayName).append('\\n')
        if (selectedAudioMode.usesTextLlm) {
            append("LLM provider: ").append(selectedTextLlmProvider.displayName)
        } else {
            append("LLM provider: managed by OpenAI Realtime Audio; text preference preserved")
        }
    }

    private fun runCapabilityProbe() {
        statusView.text = try {
            CapabilityProbe(this).run()
        } catch (error: Throwable) {
            "Capability probe failed: ${error.javaClass.simpleName}: ${error.message}"
        }
    }

    private fun runShizukuProbe(live: Boolean) {
        pendingShizukuProbe = true
        pendingShizukuLiveProbe = live

        if (!Shizuku.pingBinder()) {
            statusView.text = "Shizuku binder unavailable; start Shizuku first"
            Log.i(TAG, "shizuku_probe_binder=unavailable")
            return
        }

        if (Shizuku.isPreV11()) {
            pendingShizukuProbe = false
            pendingShizukuLiveProbe = false
            statusView.text = "Shizuku pre-v11 is unsupported"
            Log.i(TAG, "shizuku_probe_version=unsupported_pre_v11")
            return
        }

        if (Shizuku.checkSelfPermission() != PackageManager.PERMISSION_GRANTED) {
            if (Shizuku.shouldShowRequestPermissionRationale()) {
                pendingShizukuProbe = false
                pendingShizukuLiveProbe = false
                statusView.text = "Shizuku permission denied; enable it in Shizuku"
                Log.i(TAG, "shizuku_probe_permission=rationale_required")
                return
            }
            statusView.text = "Requesting Shizuku permission…"
            Log.i(TAG, "shizuku_probe_permission=requested")
            Shizuku.requestPermission(REQUEST_SHIZUKU)
            return
        }

        pendingShizukuProbe = false
        pendingShizukuLiveProbe = false
        statusView.text = if (live) {
            "Running Shizuku UserService live parity probe…"
        } else {
            "Running Shizuku UserService off-call probe…"
        }
        Log.i(TAG, if (live) "shizuku_live_probe_start=true" else "shizuku_probe_start=true")

        val callback = ShizukuUserServiceProbe.Callback { result ->
            runOnUiThread {
                statusView.text = result
                Log.i(TAG, "shizuku_probe_result:\\n$result")
            }
        }
        if (live) {
            ShizukuUserServiceProbe.runLive(this, LIVE_SHIZUKU_DURATION_MS, callback)
        } else {
            ShizukuUserServiceProbe.run(this, callback)
        }
    }

    private fun requestMicrophonePermissionIfNeeded() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            statusView.text = "Microphone permission already granted"
            return
        }

        requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_RECORD_AUDIO)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)

        if (requestCode == REQUEST_RECORD_AUDIO) {
            val granted = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
            statusView.text = if (granted) {
                "Microphone permission granted"
            } else {
                "Microphone permission denied"
            }
        }
    }

    private companion object {
        const val TAG = "AiCallBridge"
        const val REQUEST_RECORD_AUDIO = 1001
        const val REQUEST_SHIZUKU = 1002
        const val LIVE_SHIZUKU_DURATION_MS = 5_000
        const val EXTRA_RUN_CAPABILITY_PROBE = "run_probe"
    }
}
'''


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def red() -> None:
    write("app/src/test/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeModeTest.kt", TEST)
    print("runtime_selector_red_written=true")


def green() -> None:
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeMode.kt", MODE)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimePreferences.kt", PREFS)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/MainActivity.kt", MAIN)
    print("runtime_selector_green_written=true")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"red", "green"}:
        raise SystemExit("usage: runtime-mode-selectors.py red|green")
    red() if sys.argv[1] == "red" else green()
