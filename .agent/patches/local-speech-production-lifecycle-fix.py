from pathlib import Path

ROOT = Path.cwd()

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
import java.io.OutputStream
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
    private var writer: OutputStream? = null
    private val segments = mutableListOf<String>()

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

        val active = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        synchronized(lock) { recognizer = active }
        active.checkRecognitionSupport(
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
                    beginPipeRecognition(generation, listener, active)
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
            currentWriter.flush()
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
        try { currentWriter?.close() } catch (_: Throwable) {}
    }

    fun cancel() {
        gate.invalidate()
        cleanup()
    }

    override fun close() = cancel()

    private fun beginPipeRecognition(
        generation: Long,
        listener: Listener,
        active: SpeechRecognizer,
    ) {
        if (!gate.isCurrent(generation)) return
        val pipe = try {
            ParcelFileDescriptor.createPipe()
        } catch (error: Throwable) {
            finishWithError(generation, listener, "pipe_create_${error.javaClass.simpleName}")
            return
        }
        val reader = pipe[0]
        val writeStream = ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])
        synchronized(lock) {
            if (!gate.isCurrent(generation) || recognizer !== active) {
                try { reader.close() } catch (_: Throwable) {}
                try { writeStream.close() } catch (_: Throwable) {}
                return
            }
            readPfd = reader
            writer = writeStream
            segments.clear()
        }

        val request = baseIntent().apply {
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, reader)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, LocalSpeechFormat.CHANNEL_COUNT)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
            putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, LocalSpeechFormat.SAMPLE_RATE_HZ)
            putExtra(RecognizerIntent.EXTRA_SEGMENTED_SESSION, RecognizerIntent.EXTRA_AUDIO_SOURCE)
        }

        active.setRecognitionListener(object : RecognitionListener {
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
                val top = segmentResults
                    .getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    .orEmpty()
                if (top.isNotBlank()) synchronized(lock) { segments += top }
            }

            override fun onEndOfSegmentedSession() {
                if (!gate.isCurrent(generation)) return
                completeTranscript(generation, listener, "")
            }

            override fun onError(error: Int) {
                finishWithError(generation, listener, "recognition_error_$error")
            }

            override fun onResults(results: Bundle?) {
                if (!gate.isCurrent(generation)) return
                val direct = results
                    ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    ?.firstOrNull()
                    .orEmpty()
                completeTranscript(generation, listener, direct)
            }
        })

        try {
            active.startListening(request)
        } catch (error: Throwable) {
            finishWithError(generation, listener, "start_listening_${error.javaClass.simpleName}")
        }
    }

    private fun completeTranscript(generation: Long, listener: Listener, direct: String) {
        if (!gate.isCurrent(generation)) return
        val segmented = synchronized(lock) { segments.joinToString(" ") }
        val text = direct.ifBlank { segmented }
        if (text.isBlank()) {
            finishWithError(generation, listener, "empty_transcript")
            return
        }
        finishGeneration(generation)
        listener.onFinalTranscript(text)
    }

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
        val currentRecognizer: SpeechRecognizer?
        val currentRead: ParcelFileDescriptor?
        val currentWriter: OutputStream?
        synchronized(lock) {
            currentRecognizer = recognizer
            currentRead = readPfd
            currentWriter = writer
            recognizer = null
            readPfd = null
            writer = null
            segments.clear()
        }
        try { currentWriter?.close() } catch (_: Throwable) {}
        try { currentRead?.close() } catch (_: Throwable) {}
        try { currentRecognizer?.cancel() } catch (_: Throwable) {}
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
        Locale.forLanguageTag(tag).language.equals(
            Locale.forLanguageTag(languageTag).language,
            ignoreCase = true,
        )
}
'''

path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/OnDeviceSpeechInput.kt"
path.write_text(INPUT, encoding="utf-8")

probe_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechProductionProbe.kt"
probe = probe_path.read_text(encoding="utf-8")
old = '''                                val silence = ByteArray(LocalSpeechFormat.bytesForDurationMs(500))
                                val chunk = LocalSpeechFormat.bytesForDurationMs(20)
                                input.writePcm(silence)
                                var offset = 0
                                while (offset < pcm.size) {
                                    val length = minOf(chunk, pcm.size - offset)
                                    if (!input.writePcm(pcm, offset, length)) {
                                        appContext.mainExecutor.execute { finish(false, "stt_pipe_write_failed") }
                                        return@Thread
                                    }
                                    offset += length
                                    Thread.sleep(20L)
                                }
                                input.writePcm(silence)
                                input.finishInput()
'''
new = '''                                val silence = ByteArray(LocalSpeechFormat.bytesForDurationMs(500))
                                val chunk = LocalSpeechFormat.bytesForDurationMs(20)

                                fun writePaced(data: ByteArray): Boolean {
                                    var offset = 0
                                    while (offset < data.size) {
                                        val length = minOf(chunk, data.size - offset)
                                        if (!input.writePcm(data, offset, length)) return false
                                        offset += length
                                        Thread.sleep(20L)
                                    }
                                    return true
                                }

                                if (!writePaced(silence) || !writePaced(pcm) || !writePaced(silence)) {
                                    appContext.mainExecutor.execute { finish(false, "stt_pipe_write_failed") }
                                    return@Thread
                                }
                                input.finishInput()
'''
if probe.count(old) != 1:
    raise RuntimeError(f"production probe pacing block: expected 1 match, got {probe.count(old)}")
probe_path.write_text(probe.replace(old, new, 1), encoding="utf-8")
print("local_speech_production_lifecycle_fix_applied=true")
