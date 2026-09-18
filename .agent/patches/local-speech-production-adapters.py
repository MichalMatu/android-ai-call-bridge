from pathlib import Path
import sys

ROOT = Path.cwd()

TEST = r'''package pl.michalmatu.aicallbridge.localspeech

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalSpeechProductionContractsTest {
    @Test
    fun telephonySpeechFormatIsFixedToMonoPcm16At16k() {
        assertEquals(16_000, LocalSpeechFormat.SAMPLE_RATE_HZ)
        assertEquals(1, LocalSpeechFormat.CHANNEL_COUNT)
        assertEquals(2, LocalSpeechFormat.BYTES_PER_SAMPLE)
        assertEquals(640, LocalSpeechFormat.bytesForDurationMs(20))
    }

    @Test
    fun generationGateInvalidatesOlderCallbacks() {
        val gate = LocalSpeechGenerationGate()
        val first = gate.begin()
        assertTrue(gate.isCurrent(first))

        val second = gate.begin()
        assertFalse(gate.isCurrent(first))
        assertTrue(gate.isCurrent(second))

        gate.invalidate()
        assertFalse(gate.isCurrent(second))
    }
}
'''

FORMAT = r'''package pl.michalmatu.aicallbridge.localspeech

internal object LocalSpeechFormat {
    const val SAMPLE_RATE_HZ = 16_000
    const val CHANNEL_COUNT = 1
    const val BYTES_PER_SAMPLE = 2

    fun bytesForDurationMs(durationMs: Int): Int {
        require(durationMs >= 0) { "duration_must_be_non_negative" }
        return SAMPLE_RATE_HZ * CHANNEL_COUNT * BYTES_PER_SAMPLE * durationMs / 1_000
    }
}
'''

GENERATION = r'''package pl.michalmatu.aicallbridge.localspeech

internal class LocalSpeechGenerationGate {
    private var generation = 0L

    @Synchronized
    fun begin(): Long {
        generation += 1L
        return generation
    }

    @Synchronized
    fun invalidate() {
        generation += 1L
    }

    @Synchronized
    fun isCurrent(candidate: Long): Boolean = generation == candidate
}
'''

INPUT = r'''package pl.michalmatu.aicallbridge.localspeech

import android.Manifest
import android.annotation.TargetApi
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.os.Bundle
import android.os.ParcelFileDescriptor
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import java.io.FileOutputStream
import java.util.Locale

@TargetApi(34)
internal class OnDeviceSpeechInput(
    context: Context,
    private val languageTag: String = "pl-PL",
) : AutoCloseable {
    interface Listener {
        fun onReady()
        fun onFinalTranscript(text: String)
        fun onError(reason: String)
    }

    private val appContext = context.applicationContext
    private val gate = LocalSpeechGenerationGate()
    private val lock = Any()
    private var recognizer: SpeechRecognizer? = null
    private var readPfd: ParcelFileDescriptor? = null
    private var writer: FileOutputStream? = null
    private var latestSegment: String = ""

    fun start(listener: Listener) {
        cancel()
        val generation = gate.begin()
        if (android.os.Build.VERSION.SDK_INT < 34) {
            listener.onError("api_below_34")
            return
        }
        if (appContext.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            listener.onError("record_audio_permission_missing")
            return
        }
        if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)) {
            listener.onError("on_device_recognizer_unavailable")
            return
        }

        val supportRecognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        synchronized(lock) { recognizer = supportRecognizer }
        supportRecognizer.checkRecognitionSupport(
            baseIntent(),
            appContext.mainExecutor,
            object : RecognitionSupportCallback {
                override fun onSupportResult(recognitionSupport: RecognitionSupport) {
                    if (!gate.isCurrent(generation)) return
                    val installed = recognitionSupport.installedOnDeviceLanguages.any(::isSelectedLanguage)
                    if (!installed) {
                        finishWithError(generation, listener, "language_model_not_installed")
                        return
                    }
                    try {
                        supportRecognizer.destroy()
                    } catch (_: Throwable) {
                    }
                    synchronized(lock) {
                        if (recognizer === supportRecognizer) recognizer = null
                    }
                    beginPipeRecognition(generation, listener)
                }

                override fun onError(error: Int) {
                    finishWithError(generation, listener, "support_check_error_$error")
                }
            },
        )
    }

    fun writePcm(bytes: ByteArray, offset: Int = 0, length: Int = bytes.size): Boolean {
        require(offset >= 0 && length >= 0 && offset + length <= bytes.size) { "invalid_pcm_range" }
        val currentWriter = synchronized(lock) { writer } ?: return false
        return try {
            currentWriter.write(bytes, offset, length)
            true
        } catch (_: Throwable) {
            false
        }
    }

    fun finishInput() {
        val currentWriter = synchronized(lock) {
            val value = writer
            writer = null
            value
        }
        try {
            currentWriter?.close()
        } catch (_: Throwable) {
        }
    }

    fun cancel() {
        gate.invalidate()
        val currentRecognizer: SpeechRecognizer?
        val currentRead: ParcelFileDescriptor?
        val currentWriter: FileOutputStream?
        synchronized(lock) {
            currentRecognizer = recognizer
            currentRead = readPfd
            currentWriter = writer
            recognizer = null
            readPfd = null
            writer = null
            latestSegment = ""
        }
        try { currentWriter?.close() } catch (_: Throwable) {}
        try { currentRead?.close() } catch (_: Throwable) {}
        try { currentRecognizer?.cancel() } catch (_: Throwable) {}
        try { currentRecognizer?.destroy() } catch (_: Throwable) {}
    }

    override fun close() = cancel()

    private fun beginPipeRecognition(generation: Long, listener: Listener) {
        if (!gate.isCurrent(generation)) return
        val pipe = try {
            ParcelFileDescriptor.createPipe()
        } catch (error: Throwable) {
            finishWithError(generation, listener, "pipe_create_${error.javaClass.simpleName}")
            return
        }
        val reader = pipe[0]
        val writeStream = FileOutputStream(pipe[1].fileDescriptor)
        val recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        synchronized(lock) {
            if (!gate.isCurrent(generation)) {
                try { reader.close() } catch (_: Throwable) {}
                try { writeStream.close() } catch (_: Throwable) {}
                try { pipe[1].close() } catch (_: Throwable) {}
                try { recognizer.destroy() } catch (_: Throwable) {}
                return
            }
            this.recognizer = recognizer
            readPfd = reader
            writer = writeStream
            latestSegment = ""
        }

        val request = baseIntent().apply {
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, reader)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, LocalSpeechFormat.CHANNEL_COUNT)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, LocalSpeechFormat.SAMPLE_RATE_HZ)
            putExtra(RecognizerIntent.EXTRA_SEGMENTED_SESSION, RecognizerIntent.EXTRA_AUDIO_SOURCE)
        }

        recognizer.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                if (gate.isCurrent(generation)) listener.onReady()
            }
            override fun onBeginningOfSpeech() = Unit
            override fun onRmsChanged(rmsdB: Float) = Unit
            override fun onBufferReceived(buffer: ByteArray?) = Unit
            override fun onEndOfSpeech() = Unit
            override fun onPartialResults(partialResults: Bundle?) = Unit
            override fun onEvent(eventType: Int, params: Bundle?) = Unit

            override fun onSegmentResults(segmentResults: Bundle) {
                if (!gate.isCurrent(generation)) return
                val top = segmentResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                if (top.isNotBlank()) synchronized(lock) { latestSegment = top }
            }

            override fun onEndOfSegmentedSession() = Unit

            override fun onError(error: Int) {
                finishWithError(generation, listener, "recognition_error_$error")
            }

            override fun onResults(results: Bundle?) {
                if (!gate.isCurrent(generation)) return
                val direct = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                val text = if (direct.isNotBlank()) direct else synchronized(lock) { latestSegment }
                if (text.isBlank()) {
                    finishWithError(generation, listener, "empty_transcript")
                    return
                }
                finishGeneration(generation)
                listener.onFinalTranscript(text)
            }
        })

        try {
            recognizer.startListening(request)
        } catch (error: Throwable) {
            finishWithError(generation, listener, "start_listening_${error.javaClass.simpleName}")
        }
    }

    private fun finishWithError(generation: Long, listener: Listener, reason: String) {
        if (!gate.isCurrent(generation)) return
        finishGeneration(generation)
        listener.onError(reason)
    }

    private fun finishGeneration(generation: Long) {
        if (!gate.isCurrent(generation)) return
        gate.invalidate()
        val currentRecognizer: SpeechRecognizer?
        val currentRead: ParcelFileDescriptor?
        val currentWriter: FileOutputStream?
        synchronized(lock) {
            currentRecognizer = recognizer
            currentRead = readPfd
            currentWriter = writer
            recognizer = null
            readPfd = null
            writer = null
            latestSegment = ""
        }
        try { currentWriter?.close() } catch (_: Throwable) {}
        try { currentRead?.close() } catch (_: Throwable) {}
        try { currentRecognizer?.destroy() } catch (_: Throwable) {}
    }

    private fun baseIntent(): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
        putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
        putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
    }

    private fun isSelectedLanguage(tag: String): Boolean =
        Locale.forLanguageTag(tag).language.equals(Locale.forLanguageTag(languageTag).language, ignoreCase = true)
}
'''

OUTPUT = r'''package pl.michalmatu.aicallbridge.localspeech

import android.content.Context
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.io.File
import java.util.Locale
import java.util.UUID

internal class LocalTtsSpeechOutput(
    context: Context,
    private val languageTag: String = "pl-PL",
) : AutoCloseable {
    interface Listener {
        fun onPcm16Mono16k(pcm: ByteArray)
        fun onError(reason: String)
    }

    private val appContext = context.applicationContext
    private val gate = LocalSpeechGenerationGate()
    private val lock = Any()
    private var engine: TextToSpeech? = null
    private var outputFile: File? = null

    fun synthesize(text: String, listener: Listener) {
        require(text.isNotBlank()) { "text_must_not_be_blank" }
        cancel()
        val generation = gate.begin()
        val holder = arrayOfNulls<TextToSpeech>(1)
        holder[0] = TextToSpeech(appContext) { status ->
            appContext.mainExecutor.execute {
                if (!gate.isCurrent(generation)) {
                    try { holder[0]?.shutdown() } catch (_: Throwable) {}
                    return@execute
                }
                val tts = holder[0]
                if (status != TextToSpeech.SUCCESS || tts == null) {
                    finishWithError(generation, listener, "tts_init_failed")
                    return@execute
                }
                synchronized(lock) { engine = tts }
                val selectedLanguage = Locale.forLanguageTag(languageTag).language
                val localVoice = tts.voices.orEmpty()
                    .filter { it.locale.language.equals(selectedLanguage, ignoreCase = true) && !it.isNetworkConnectionRequired }
                    .sortedBy { it.name }
                    .firstOrNull()
                if (localVoice == null) {
                    finishWithError(generation, listener, "local_voice_missing")
                    return@execute
                }
                if (tts.setVoice(localVoice) != TextToSpeech.SUCCESS) {
                    finishWithError(generation, listener, "tts_set_voice_failed")
                    return@execute
                }

                val waveFile = File(appContext.cacheDir, "local-speech-${UUID.randomUUID()}.wav")
                synchronized(lock) { outputFile = waveFile }
                tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String?) = Unit
                    override fun onDone(utteranceId: String?) {
                        appContext.mainExecutor.execute {
                            if (!gate.isCurrent(generation)) return@execute
                            try {
                                val decoded = LocalSpeechPcm.decodeWaveToMonoPcm16(waveFile.readBytes())
                                val target = LocalSpeechPcm.resampleLinear(
                                    decoded.monoSamples,
                                    decoded.sampleRate,
                                    LocalSpeechFormat.SAMPLE_RATE_HZ,
                                )
                                val raw = LocalSpeechPcm.toLittleEndianBytes(target)
                                if (raw.isEmpty()) {
                                    finishWithError(generation, listener, "tts_empty_pcm")
                                    return@execute
                                }
                                finishGeneration(generation)
                                listener.onPcm16Mono16k(raw)
                            } catch (error: Throwable) {
                                finishWithError(generation, listener, "tts_decode_${error.javaClass.simpleName}")
                            }
                        }
                    }

                    @Deprecated("Deprecated by framework")
                    override fun onError(utteranceId: String?) {
                        finishWithError(generation, listener, "tts_synthesis_error")
                    }

                    override fun onError(utteranceId: String?, errorCode: Int) {
                        finishWithError(generation, listener, "tts_synthesis_error_$errorCode")
                    }
                })
                val result = tts.synthesizeToFile(text, Bundle.EMPTY, waveFile, "local-speech-$generation")
                if (result != TextToSpeech.SUCCESS) {
                    finishWithError(generation, listener, "tts_queue_failed")
                }
            }
        }
    }

    fun cancel() {
        gate.invalidate()
        cleanup()
    }

    override fun close() = cancel()

    private fun finishWithError(generation: Long, listener: Listener, reason: String) {
        if (!gate.isCurrent(generation)) return
        finishGeneration(generation)
        listener.onError(reason)
    }

    private fun finishGeneration(generation: Long) {
        if (!gate.isCurrent(generation)) return
        gate.invalidate()
        cleanup()
    }

    private fun cleanup() {
        val currentEngine: TextToSpeech?
        val currentFile: File?
        synchronized(lock) {
            currentEngine = engine
            currentFile = outputFile
            engine = null
            outputFile = null
        }
        try { currentEngine?.stop() } catch (_: Throwable) {}
        try { currentEngine?.shutdown() } catch (_: Throwable) {}
        try { currentFile?.delete() } catch (_: Throwable) {}
    }
}
'''

PROBE = r'''package pl.michalmatu.aicallbridge

import android.content.Context
import android.os.Handler
import android.os.Looper
import pl.michalmatu.aicallbridge.localspeech.LocalSpeechFormat
import pl.michalmatu.aicallbridge.localspeech.LocalTtsSpeechOutput
import pl.michalmatu.aicallbridge.localspeech.OnDeviceSpeechInput
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call proof that production local speech adapters round-trip on the exact S22. */
object LocalSpeechProductionProbe {
    private const val TEST_TEXT = "To jest test lokalnego rozpoznawania mowy."
    private const val REPORT_FILE = "local-speech-production-report.txt"
    private const val TIMEOUT_MS = 30_000L

    fun run(context: Context, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val input = OnDeviceSpeechInput(appContext)
        val output = LocalTtsSpeechOutput(appContext)
        val handler = Handler(Looper.getMainLooper())
        val finished = AtomicBoolean(false)
        val lines = mutableListOf<String>()

        fun finish(success: Boolean, reason: String? = null) {
            if (!finished.compareAndSet(false, true)) return
            handler.removeCallbacksAndMessages(null)
            input.close()
            output.close()
            lines += "production_roundtrip_success=$success"
            if (reason != null) lines += "failure_reason=$reason"
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            File(appContext.filesDir, REPORT_FILE).writeText(report)
            callback(report)
        }

        lines += "probe_version=1"
        lines += "timestamp_utc=${Instant.now()}"
        lines += "test_text=$TEST_TEXT"
        lines += "target_pcm=mono,pcm16,${LocalSpeechFormat.SAMPLE_RATE_HZ}"
        handler.postDelayed({ finish(false, "probe_timeout") }, TIMEOUT_MS)

        output.synthesize(TEST_TEXT, object : LocalTtsSpeechOutput.Listener {
            override fun onPcm16Mono16k(pcm: ByteArray) {
                lines += "tts_pcm_bytes=${pcm.size}"
                input.start(object : OnDeviceSpeechInput.Listener {
                    override fun onReady() {
                        lines += "stt_ready=true"
                        Thread {
                            try {
                                val silence = ByteArray(LocalSpeechFormat.bytesForDurationMs(500))
                                val chunk = LocalSpeechFormat.bytesForDurationMs(20)
                                input.writePcm(silence)
                                var offset = 0
                                while (offset < pcm.size) {
                                    val length = minOf(chunk, pcm.size - offset)
                                    if (!input.writePcm(pcm, offset, length)) {
                                        appContext.mainExecutor.execute { finish(false, "pcm_write_failed") }
                                        return@Thread
                                    }
                                    offset += length
                                    Thread.sleep(20L)
                                }
                                input.writePcm(silence)
                                input.finishInput()
                                lines += "pcm_eof_sent=true"
                            } catch (error: Throwable) {
                                appContext.mainExecutor.execute { finish(false, "stream_${error.javaClass.simpleName}") }
                            }
                        }.start()
                    }

                    override fun onFinalTranscript(text: String) {
                        lines += "stt_text=$text"
                        val normalized = normalize(text)
                        val success = normalized.contains("test") &&
                            normalized.contains("lokal") &&
                            normalized.contains("rozpozn")
                        finish(success, if (success) null else "unexpected_transcript")
                    }

                    override fun onError(reason: String) {
                        finish(false, "stt_$reason")
                    }
                })
            }

            override fun onError(reason: String) {
                finish(false, "tts_$reason")
            }
        })
    }

    private fun normalize(value: String): String = value
        .lowercase(Locale.forLanguageTag("pl-PL"))
        .replace(Regex("[^a-ząćęłńóśźż0-9 ]"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()
}
'''


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def red() -> None:
    write("app/src/test/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechProductionContractsTest.kt", TEST)
    print("local_speech_production_red_written=true")


def green() -> None:
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechFormat.kt", FORMAT)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechGenerationGate.kt", GENERATION)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/OnDeviceSpeechInput.kt", INPUT)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalTtsSpeechOutput.kt", OUTPUT)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechProductionProbe.kt", PROBE)

    activity_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
    activity = activity_path.read_text(encoding="utf-8")
    activity = replace_once(
        activity,
        "    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PFD_LOOPBACK_PROBE, false)) {\n",
        '''    private fun runRequestedProbe() {
        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE, false)) {
            statusView.text = "Running production local speech adapter probe…"
            Log.i(TAG, "local_speech_production_probe_start=true")
            LocalSpeechProductionProbe.run(this) { result ->
                runOnUiThread {
                    statusView.text = result
                    Log.i(TAG, "local_speech_production_probe_result:\\n$result")
                    finish()
                }
            }
            return
        }

        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PFD_LOOPBACK_PROBE, false)) {
''',
        "production probe dispatch",
    )
    activity = replace_once(
        activity,
        '        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n',
        '        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n        const val EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE = "run_local_speech_production_probe"\n',
        "production probe constant",
    )
    activity_path.write_text(activity, encoding="utf-8")
    print("local_speech_production_green_written=true")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"red", "green"}:
        raise SystemExit("usage: local-speech-production-adapters.py red|green")
    red() if sys.argv[1] == "red" else green()
