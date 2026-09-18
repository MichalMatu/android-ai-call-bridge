from pathlib import Path

ROOT = Path.cwd()

PROBE = r'''package pl.michalmatu.aicallbridge

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call, network-independent capability probe for the LOCAL_STT_TTS path. */
object LocalSpeechCapabilityProbe {
    private const val LANGUAGE_TAG = "pl-PL"
    private const val REPORT_FILE_NAME = "local-speech-capability-report.txt"
    private const val TTS_UTTERANCE_ID = "local-speech-capability-probe"

    fun run(context: Context, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val lines = mutableListOf<String>()
        lines += "probe_version=1"
        lines += "timestamp_utc=${Instant.now()}"
        lines += "language=$LANGUAGE_TAG"
        lines += "sdk=${Build.VERSION.SDK_INT}"
        lines += "recognition_available=${SpeechRecognizer.isRecognitionAvailable(appContext)}"

        val onDeviceAvailable = Build.VERSION.SDK_INT >= 31 &&
            SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)
        lines += "on_device_recognition_available=$onDeviceAvailable"
        lines += "audio_source_pfd_api_available=${Build.VERSION.SDK_INT >= 33}"
        lines += "target_pcm_format=mono,pcm16,16000"

        if (!onDeviceAvailable) {
            lines += "stt_support_probe=unavailable"
            runTtsProbe(appContext, lines, callback)
            return
        }

        val recognizer = try {
            SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        } catch (error: Throwable) {
            lines += "stt_create_error=${sanitize(error.javaClass.simpleName)}"
            runTtsProbe(appContext, lines, callback)
            return
        }

        if (Build.VERSION.SDK_INT < 33) {
            lines += "stt_support_probe=api_below_33"
            recognizer.destroy()
            runTtsProbe(appContext, lines, callback)
            return
        }

        val request = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, LANGUAGE_TAG)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
        }

        try {
            recognizer.checkRecognitionSupport(
                request,
                appContext.mainExecutor,
                object : RecognitionSupportCallback {
                    override fun onSupportResult(recognitionSupport: RecognitionSupport) {
                        lines += "stt_support_probe=ok"
                        lines += "stt_installed_on_device_languages=${languageList(recognitionSupport.installedOnDeviceLanguages)}"
                        lines += "stt_supported_on_device_languages=${languageList(recognitionSupport.supportedOnDeviceLanguages)}"
                        lines += "stt_pending_on_device_languages=${languageList(recognitionSupport.pendingOnDeviceLanguages)}"
                        lines += "stt_online_languages=${languageList(recognitionSupport.onlineLanguages)}"
                        lines += "stt_pl_installed=${containsPolish(recognitionSupport.installedOnDeviceLanguages)}"
                        lines += "stt_pl_supported_downloadable=${containsPolish(recognitionSupport.supportedOnDeviceLanguages)}"
                        recognizer.destroy()
                        runTtsProbe(appContext, lines, callback)
                    }

                    override fun onError(error: Int) {
                        lines += "stt_support_probe=error:$error"
                        recognizer.destroy()
                        runTtsProbe(appContext, lines, callback)
                    }
                },
            )
        } catch (error: Throwable) {
            lines += "stt_support_probe=exception:${sanitize(error.javaClass.simpleName)}"
            recognizer.destroy()
            runTtsProbe(appContext, lines, callback)
        }
    }

    private fun runTtsProbe(
        context: Context,
        lines: MutableList<String>,
        callback: (String) -> Unit,
    ) {
        val finished = AtomicBoolean(false)
        val holder = arrayOfNulls<TextToSpeech>(1)

        fun finish(engine: TextToSpeech?) {
            if (!finished.compareAndSet(false, true)) return
            try {
                engine?.shutdown()
            } catch (_: Throwable) {
                // Probe cleanup must not hide the primary result.
            }
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            File(context.filesDir, REPORT_FILE_NAME).writeText(report)
            callback(report)
        }

        holder[0] = TextToSpeech(context) { status ->
            context.mainExecutor.execute {
                val engine = holder[0]
                lines += "tts_init_status=$status"
                if (status != TextToSpeech.SUCCESS || engine == null) {
                    lines += "tts_probe=init_failed"
                    finish(engine)
                    return@execute
                }

                val locale = Locale.forLanguageTag(LANGUAGE_TAG)
                val languageStatus = engine.isLanguageAvailable(locale)
                lines += "tts_pl_language_status=$languageStatus"

                val polishVoices = engine.voices.orEmpty()
                    .filter { it.locale.language.equals("pl", ignoreCase = true) }
                    .sortedBy { it.name }
                val localPolishVoices = polishVoices.filterNot { it.isNetworkConnectionRequired }
                lines += "tts_polish_voice_count=${polishVoices.size}"
                lines += "tts_polish_local_voice_count=${localPolishVoices.size}"
                lines += "tts_polish_local_voices=${localPolishVoices.joinToString(",") { sanitize(it.name) }.ifEmpty { "none" }}"

                val localVoice = localPolishVoices.firstOrNull()
                if (localVoice == null) {
                    lines += "tts_local_pl_voice_available=false"
                    finish(engine)
                    return@execute
                }

                lines += "tts_local_pl_voice_available=true"
                lines += "tts_selected_voice=${sanitize(localVoice.name)}"
                lines += "tts_selected_voice_network_required=${localVoice.isNetworkConnectionRequired}"
                lines += "tts_set_voice_result=${engine.setVoice(localVoice)}"

                val output = File(context.cacheDir, "local-speech-capability-probe.wav")
                output.delete()
                engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = Unit

                    override fun onDone(utteranceId: String?) {
                        context.mainExecutor.execute {
                            lines += "tts_synthesis_done=true"
                            lines += "tts_synthesis_file_bytes=${output.length()}"
                            lines += "tts_synthesis_nonempty=${output.length() > 0L}"
                            output.delete()
                            finish(engine)
                        }
                    }

                    @Deprecated("Deprecated by framework")
                    override fun onError(utteranceId: String?) {
                        context.mainExecutor.execute {
                            lines += "tts_synthesis_done=false"
                            lines += "tts_synthesis_error=legacy"
                            output.delete()
                            finish(engine)
                        }
                    }

                    override fun onError(utteranceId: String?, errorCode: Int) {
                        context.mainExecutor.execute {
                            lines += "tts_synthesis_done=false"
                            lines += "tts_synthesis_error=$errorCode"
                            output.delete()
                            finish(engine)
                        }
                    }
                })

                val queued = engine.synthesizeToFile(
                    "To jest test lokalnej syntezy mowy.",
                    Bundle.EMPTY,
                    output,
                    TTS_UTTERANCE_ID,
                )
                lines += "tts_synthesize_queue_result=$queued"
                if (queued != TextToSpeech.SUCCESS) {
                    output.delete()
                    finish(engine)
                }
            }
        }
    }

    private fun containsPolish(languages: List<String>): Boolean =
        languages.any { Locale.forLanguageTag(it).language.equals("pl", ignoreCase = true) }

    private fun languageList(languages: List<String>): String =
        languages.sorted().joinToString(",") { sanitize(it) }.ifEmpty { "none" }

    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').replace(',', ';')
}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    probe_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechCapabilityProbe.kt"
    probe_path.write_text(PROBE, encoding="utf-8")

    activity_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
    activity = activity_path.read_text(encoding="utf-8")
    activity = replace_once(
        activity,
        "    private fun runRequestedProbe() {\n        if (!Shizuku.pingBinder()) {\n",
        '''    private fun runRequestedProbe() {
        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE, false)) {
            statusView.text = "Running local STT/TTS capability probe…"
            Log.i(TAG, "local_speech_capability_probe_start=true")
            LocalSpeechCapabilityProbe.run(this) { result ->
                runOnUiThread {
                    statusView.text = result
                    Log.i(TAG, "local_speech_capability_probe_result:\\n$result")
                    finish()
                }
            }
            return
        }

        if (!Shizuku.pingBinder()) {
''',
        "local speech probe dispatch",
    )
    activity = replace_once(
        activity,
        "        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n",
        "        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = \"run_local_speech_capability_probe\"\n",
        "local speech probe constant",
    )
    activity_path.write_text(activity, encoding="utf-8")

    manifest_path = ROOT / "app/src/main/AndroidManifest.xml"
    manifest = manifest_path.read_text(encoding="utf-8")
    manifest = replace_once(
        manifest,
        "    <uses-permission android:name=\"moe.shizuku.manager.permission.API_V23\" />\n\n",
        '''    <uses-permission android:name="moe.shizuku.manager.permission.API_V23" />

    <queries>
        <intent>
            <action android:name="android.speech.RecognitionService" />
        </intent>
        <intent>
            <action android:name="android.intent.action.TTS_SERVICE" />
        </intent>
    </queries>

''',
        "speech service package visibility",
    )
    manifest_path.write_text(manifest, encoding="utf-8")
    print("local_speech_capability_probe_patch_applied=true")


if __name__ == "__main__":
    main()
