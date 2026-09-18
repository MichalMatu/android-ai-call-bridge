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
        assertEquals(CallAudioMode.LOCAL_REALTIME_AUDIO, CallAudioMode.fromStored("LOCAL_REALTIME_AUDIO"))
        assertEquals(TextLlmProvider.LOCAL_MAC_LLM, TextLlmProvider.fromStored("LOCAL_MAC_LLM"))
        assertEquals(CallAudioMode.LOCAL_STT_TTS, CallAudioMode.fromStored("unknown"))
        assertEquals(TextLlmProvider.OPENAI_TEXT, TextLlmProvider.fromStored(null))
    }

    @Test
    fun realtimeAudioModesDoNotUseTextLlmButKeepIndependentTextPreference() {
        listOf(
            CallAudioMode.OPENAI_REALTIME_AUDIO,
            CallAudioMode.LOCAL_REALTIME_AUDIO,
        ).forEach { audioMode ->
            val selection = CallRuntimeSelection(
                audioMode = audioMode,
                textLlmProvider = TextLlmProvider.LOCAL_MAC_LLM,
            )

            assertFalse(selection.audioMode.usesTextLlm)
            assertEquals(TextLlmProvider.LOCAL_MAC_LLM, selection.textLlmProvider)
        }
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
    LOCAL_REALTIME_AUDIO("Local Realtime Audio (server)", false),
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


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {text.count(old)}")
    return text.replace(old, new, 1)


def red() -> None:
    write("app/src/test/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeModeTest.kt", TEST)
    print("runtime_selector_red_written=true")


def green() -> None:
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeMode.kt", MODE)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimePreferences.kt", PREFS)

    main_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/MainActivity.kt"
    main = main_path.read_text(encoding="utf-8")
    main = replace_once(
        main,
        "import android.widget.Button\nimport android.widget.LinearLayout\nimport android.widget.ScrollView\nimport android.widget.TextView\n",
        "import android.widget.AdapterView\nimport android.widget.ArrayAdapter\nimport android.widget.Button\nimport android.widget.LinearLayout\nimport android.widget.ScrollView\nimport android.widget.Spinner\nimport android.widget.TextView\n",
        "widget imports",
    )
    main = replace_once(
        main,
        "import pl.michalmatu.aicallbridge.shizuku.ShizukuUserServiceProbe\n",
        "import pl.michalmatu.aicallbridge.runtime.CallAudioMode\nimport pl.michalmatu.aicallbridge.runtime.CallRuntimePreferences\nimport pl.michalmatu.aicallbridge.runtime.TextLlmProvider\nimport pl.michalmatu.aicallbridge.shizuku.ShizukuUserServiceProbe\n",
        "runtime imports",
    )
    main = replace_once(
        main,
        "    private lateinit var statusView: TextView\n    private var pendingShizukuProbe = false\n",
        "    private lateinit var statusView: TextView\n    private lateinit var runtimePreferences: CallRuntimePreferences\n    private lateinit var selectedAudioMode: CallAudioMode\n    private lateinit var selectedTextLlmProvider: TextLlmProvider\n    private lateinit var textLlmProviderSpinner: Spinner\n    private var pendingShizukuProbe = false\n",
        "runtime fields",
    )
    main = replace_once(
        main,
        "        super.onCreate(savedInstanceState)\n\n        statusView = TextView(this).apply {\n            text = \"Phase 2: local call bridge probes\"\n",
        "        super.onCreate(savedInstanceState)\n\n        runtimePreferences = CallRuntimePreferences(this)\n        val initialSelection = runtimePreferences.load()\n        selectedAudioMode = initialSelection.audioMode\n        selectedTextLlmProvider = initialSelection.textLlmProvider\n\n        statusView = TextView(this).apply {\n            text = runtimeSelectionSummary()\n",
        "runtime initialization",
    )
    main = replace_once(
        main,
        "        val requestMicButton = Button(this).apply {\n",
        '''        val audioModeSpinner = Spinner(this).apply {
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
''',
        "runtime spinners",
    )
    main = replace_once(
        main,
        '''            addView(TextView(this@MainActivity).apply {
                text = "Android AI Call Bridge"
                textSize = 24f
            })
            addView(requestMicButton)
''',
        '''            addView(TextView(this@MainActivity).apply {
                text = "Android AI Call Bridge"
                textSize = 24f
            })
            addView(TextView(this@MainActivity).apply { text = "Audio mode" })
            addView(audioModeSpinner)
            addView(TextView(this@MainActivity).apply { text = "LLM provider (text mode)" })
            addView(textLlmProviderSpinner)
            addView(requestMicButton)
''',
        "runtime controls",
    )
    main = replace_once(
        main,
        "    private fun runCapabilityProbe() {\n",
        '''    private fun runtimeSelectionSummary(): String = buildString {
        append("Audio mode: ").append(selectedAudioMode.displayName).append('\\n')
        when (selectedAudioMode) {
            CallAudioMode.LOCAL_STT_TTS -> append("LLM provider: ").append(selectedTextLlmProvider.displayName)
            CallAudioMode.OPENAI_REALTIME_AUDIO -> append("LLM provider: OpenAI Realtime audio; text preference preserved")
            CallAudioMode.LOCAL_REALTIME_AUDIO -> append("LLM provider: local realtime audio engine; text preference preserved")
        }
    }

    private fun runCapabilityProbe() {
''',
        "runtime summary",
    )
    main_path.write_text(main, encoding="utf-8")
    print("runtime_selector_green_written=true")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"red", "green"}:
        raise SystemExit("usage: runtime-mode-selectors-v2.py red|green")
    red() if sys.argv[1] == "red" else green()
