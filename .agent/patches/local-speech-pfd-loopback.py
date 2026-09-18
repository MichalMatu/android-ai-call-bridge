from pathlib import Path

ROOT = Path.cwd()

PCM = r'''package pl.michalmatu.aicallbridge.localspeech

import kotlin.math.roundToInt

internal data class DecodedPcm16(
    val sampleRate: Int,
    val sourceChannelCount: Int,
    val monoSamples: ShortArray,
)

internal object LocalSpeechPcm {
    fun decodeWaveToMonoPcm16(bytes: ByteArray): DecodedPcm16 {
        require(bytes.size >= 12) { "wave_too_short" }
        require(ascii(bytes, 0, 4) == "RIFF") { "wave_missing_riff" }
        require(ascii(bytes, 8, 4) == "WAVE") { "wave_missing_wave" }

        var offset = 12
        var formatCode: Int? = null
        var channelCount: Int? = null
        var sampleRate: Int? = null
        var bitsPerSample: Int? = null
        var dataOffset: Int? = null
        var dataLength: Int? = null

        while (offset + 8 <= bytes.size) {
            val chunkId = ascii(bytes, offset, 4)
            val chunkLength = u32le(bytes, offset + 4)
            val payload = offset + 8
            require(chunkLength >= 0 && payload + chunkLength <= bytes.size) { "wave_chunk_out_of_bounds" }

            when (chunkId) {
                "fmt " -> {
                    require(chunkLength >= 16) { "wave_fmt_too_short" }
                    formatCode = u16le(bytes, payload)
                    channelCount = u16le(bytes, payload + 2)
                    sampleRate = u32le(bytes, payload + 4)
                    bitsPerSample = u16le(bytes, payload + 14)
                }
                "data" -> {
                    dataOffset = payload
                    dataLength = chunkLength
                    break
                }
            }
            offset = payload + chunkLength + (chunkLength and 1)
        }

        require(formatCode == 1) { "wave_not_pcm" }
        val channels = requireNotNull(channelCount) { "wave_missing_channels" }
        require(channels > 0) { "wave_invalid_channels" }
        val rate = requireNotNull(sampleRate) { "wave_missing_sample_rate" }
        require(rate > 0) { "wave_invalid_sample_rate" }
        require(bitsPerSample == 16) { "wave_not_pcm16" }
        val start = requireNotNull(dataOffset) { "wave_missing_data" }
        val length = requireNotNull(dataLength) { "wave_missing_data_length" }
        val frameBytes = channels * 2
        require(length % frameBytes == 0) { "wave_partial_frame" }

        val frames = length / frameBytes
        val mono = ShortArray(frames)
        var cursor = start
        for (frame in 0 until frames) {
            var sum = 0L
            repeat(channels) {
                sum += s16le(bytes, cursor).toLong()
                cursor += 2
            }
            mono[frame] = (sum / channels).coerceIn(Short.MIN_VALUE.toLong(), Short.MAX_VALUE.toLong()).toShort()
        }
        return DecodedPcm16(rate, channels, mono)
    }

    fun resampleLinear(samples: ShortArray, fromRate: Int, toRate: Int): ShortArray {
        require(fromRate > 0 && toRate > 0) { "invalid_sample_rate" }
        if (samples.isEmpty()) return ShortArray(0)
        if (fromRate == toRate) return samples.copyOf()
        if (samples.size == 1) return shortArrayOf(samples[0])

        val outputSize = ((samples.size.toDouble() * toRate) / fromRate).roundToInt().coerceAtLeast(1)
        val output = ShortArray(outputSize)
        for (index in output.indices) {
            val sourcePosition = index.toDouble() * fromRate / toRate
            val left = sourcePosition.toInt().coerceIn(0, samples.lastIndex)
            val right = (left + 1).coerceAtMost(samples.lastIndex)
            val fraction = sourcePosition - left
            val interpolated = samples[left] + (samples[right] - samples[left]) * fraction
            output[index] = interpolated.roundToInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
        return output
    }

    fun toLittleEndianBytes(samples: ShortArray): ByteArray {
        val out = ByteArray(samples.size * 2)
        samples.forEachIndexed { index, sample ->
            val value = sample.toInt()
            out[index * 2] = (value and 0xff).toByte()
            out[index * 2 + 1] = ((value ushr 8) and 0xff).toByte()
        }
        return out
    }

    private fun ascii(bytes: ByteArray, offset: Int, length: Int): String =
        bytes.copyOfRange(offset, offset + length).toString(Charsets.US_ASCII)

    private fun u16le(bytes: ByteArray, offset: Int): Int =
        (bytes[offset].toInt() and 0xff) or ((bytes[offset + 1].toInt() and 0xff) shl 8)

    private fun u32le(bytes: ByteArray, offset: Int): Int =
        (bytes[offset].toInt() and 0xff) or
            ((bytes[offset + 1].toInt() and 0xff) shl 8) or
            ((bytes[offset + 2].toInt() and 0xff) shl 16) or
            ((bytes[offset + 3].toInt() and 0xff) shl 24)

    private fun s16le(bytes: ByteArray, offset: Int): Short = u16le(bytes, offset).toShort()
}
'''

TEST = r'''package pl.michalmatu.aicallbridge.localspeech

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class LocalSpeechPcmTest {
    @Test
    fun decodesMonoPcm16Wave() {
        val wave = wave(sampleRate = 8_000, channels = 1, interleaved = shortArrayOf(0, 1000, -1000, 2000))
        val decoded = LocalSpeechPcm.decodeWaveToMonoPcm16(wave)

        assertEquals(8_000, decoded.sampleRate)
        assertEquals(1, decoded.sourceChannelCount)
        assertArrayEquals(shortArrayOf(0, 1000, -1000, 2000), decoded.monoSamples)
    }

    @Test
    fun downmixesStereoByAveragingChannels() {
        val wave = wave(sampleRate = 16_000, channels = 2, interleaved = shortArrayOf(1000, 3000, -2000, 2000))
        val decoded = LocalSpeechPcm.decodeWaveToMonoPcm16(wave)

        assertEquals(2, decoded.sourceChannelCount)
        assertArrayEquals(shortArrayOf(2000, 0), decoded.monoSamples)
    }

    @Test
    fun resamplesAndSerializesPcm16LittleEndian() {
        val resampled = LocalSpeechPcm.resampleLinear(shortArrayOf(0, 1000, 2000, 3000), 8_000, 16_000)
        assertEquals(8, resampled.size)
        assertEquals(0, resampled.first().toInt())
        assertEquals(3000, resampled.last().toInt())

        assertArrayEquals(
            byteArrayOf(0x34, 0x12, 0xCC.toByte(), 0xED.toByte()),
            LocalSpeechPcm.toLittleEndianBytes(shortArrayOf(0x1234, -0x1234)),
        )
    }

    private fun wave(sampleRate: Int, channels: Int, interleaved: ShortArray): ByteArray {
        val dataLength = interleaved.size * 2
        val bytes = ByteArray(44 + dataLength)
        putAscii(bytes, 0, "RIFF")
        putU32(bytes, 4, 36 + dataLength)
        putAscii(bytes, 8, "WAVE")
        putAscii(bytes, 12, "fmt ")
        putU32(bytes, 16, 16)
        putU16(bytes, 20, 1)
        putU16(bytes, 22, channels)
        putU32(bytes, 24, sampleRate)
        putU32(bytes, 28, sampleRate * channels * 2)
        putU16(bytes, 32, channels * 2)
        putU16(bytes, 34, 16)
        putAscii(bytes, 36, "data")
        putU32(bytes, 40, dataLength)
        interleaved.forEachIndexed { index, sample -> putU16(bytes, 44 + index * 2, sample.toInt() and 0xffff) }
        return bytes
    }

    private fun putAscii(bytes: ByteArray, offset: Int, value: String) {
        value.toByteArray(Charsets.US_ASCII).copyInto(bytes, offset)
    }

    private fun putU16(bytes: ByteArray, offset: Int, value: Int) {
        bytes[offset] = (value and 0xff).toByte()
        bytes[offset + 1] = ((value ushr 8) and 0xff).toByte()
    }

    private fun putU32(bytes: ByteArray, offset: Int, value: Int) {
        bytes[offset] = (value and 0xff).toByte()
        bytes[offset + 1] = ((value ushr 8) and 0xff).toByte()
        bytes[offset + 2] = ((value ushr 16) and 0xff).toByte()
        bytes[offset + 3] = ((value ushr 24) and 0xff).toByte()
    }
}
'''

PROBE = r'''package pl.michalmatu.aicallbridge

import android.Manifest
import android.annotation.TargetApi
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.speech.ModelDownloadListener
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import pl.michalmatu.aicallbridge.localspeech.LocalSpeechPcm
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call end-to-end proof for local TTS -> PCM16/16 kHz -> PFD -> on-device STT. */
@TargetApi(34)
object LocalSpeechPfdLoopbackProbe {
    private const val LANGUAGE_TAG = "pl-PL"
    private const val REPORT_FILE_NAME = "local-speech-pfd-loopback-report.txt"
    private const val TEST_TEXT = "To jest test lokalnego rozpoznawania mowy."
    private const val TARGET_SAMPLE_RATE = 16_000
    private const val TIMEOUT_MS = 30_000L
    private const val TTS_ID = "local-speech-pfd-loopback"

    fun run(context: Context, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val lines = mutableListOf<String>()
        val finished = AtomicBoolean(false)
        val timeoutHandler = Handler(Looper.getMainLooper())
        var activeRecognizer: SpeechRecognizer? = null
        var activePfd: ParcelFileDescriptor? = null
        var activeTts: TextToSpeech? = null

        fun finish() {
            if (!finished.compareAndSet(false, true)) return
            timeoutHandler.removeCallbacksAndMessages(null)
            try { activeRecognizer?.cancel() } catch (_: Throwable) {}
            try { activeRecognizer?.destroy() } catch (_: Throwable) {}
            try { activePfd?.close() } catch (_: Throwable) {}
            try { activeTts?.shutdown() } catch (_: Throwable) {}
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            File(appContext.filesDir, REPORT_FILE_NAME).writeText(report)
            callback(report)
        }

        fun fail(reason: String) {
            lines += "loopback_success=false"
            lines += "failure_reason=${sanitize(reason)}"
            finish()
        }

        lines += "probe_version=1"
        lines += "timestamp_utc=${Instant.now()}"
        lines += "sdk=${android.os.Build.VERSION.SDK_INT}"
        lines += "language=$LANGUAGE_TAG"
        lines += "test_text=${sanitize(TEST_TEXT)}"
        lines += "target_pcm=mono,pcm16,$TARGET_SAMPLE_RATE"
        lines += "record_audio_permission=${context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED}"

        if (android.os.Build.VERSION.SDK_INT < 34) {
            fail("api_below_34")
            return
        }
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            fail("record_audio_permission_missing")
            return
        }
        if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)) {
            fail("on_device_recognizer_unavailable")
            return
        }

        timeoutHandler.postDelayed({ fail("probe_timeout") }, TIMEOUT_MS)

        fun recognitionIntent(): Intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, LANGUAGE_TAG)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }

        fun startRecognition(rawFile: File) {
            val recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
            activeRecognizer = recognizer
            val pfd = ParcelFileDescriptor.open(rawFile, ParcelFileDescriptor.MODE_READ_ONLY)
            activePfd = pfd
            val request = recognitionIntent().apply {
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, pfd)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, TARGET_SAMPLE_RATE)
            }

            recognizer.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) { lines += "stt_ready=true" }
                override fun onBeginningOfSpeech() { lines += "stt_beginning=true" }
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() { lines += "stt_end_of_speech=true" }
                override fun onError(error: Int) { fail("stt_error_$error") }
                override fun onPartialResults(partialResults: Bundle?) = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit

                override fun onResults(results: Bundle?) {
                    val hypotheses = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                    val top = hypotheses.firstOrNull().orEmpty()
                    lines += "stt_result_count=${hypotheses.size}"
                    lines += "stt_top=${sanitize(top)}"
                    val normalized = normalize(top)
                    val success = normalized.contains("test") &&
                        normalized.contains("lokal") &&
                        normalized.contains("rozpozn")
                    lines += "loopback_success=$success"
                    if (!success) lines += "failure_reason=unexpected_transcript"
                    finish()
                }
            })

            try {
                recognizer.startListening(request)
                lines += "stt_start_listening=true"
            } catch (error: Throwable) {
                fail("stt_start_${error.javaClass.simpleName}")
            }
        }

        fun synthesizeAndRecognize() {
            val holder = arrayOfNulls<TextToSpeech>(1)
            holder[0] = TextToSpeech(appContext) { status ->
                appContext.mainExecutor.execute {
                    val tts = holder[0]
                    activeTts = tts
                    lines += "tts_init_status=$status"
                    if (status != TextToSpeech.SUCCESS || tts == null) {
                        fail("tts_init_failed")
                        return@execute
                    }
                    val localVoice = tts.voices.orEmpty()
                        .filter { it.locale.language.equals("pl", ignoreCase = true) && !it.isNetworkConnectionRequired }
                        .sortedBy { it.name }
                        .firstOrNull()
                    if (localVoice == null) {
                        fail("local_polish_tts_voice_missing")
                        return@execute
                    }
                    lines += "tts_voice=${sanitize(localVoice.name)}"
                    lines += "tts_voice_network_required=${localVoice.isNetworkConnectionRequired}"
                    if (tts.setVoice(localVoice) != TextToSpeech.SUCCESS) {
                        fail("tts_set_voice_failed")
                        return@execute
                    }

                    val waveFile = File(appContext.cacheDir, "local-speech-pfd-loopback.wav").apply { delete() }
                    val rawFile = File(appContext.cacheDir, "local-speech-pfd-loopback.pcm").apply { delete() }
                    tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) = Unit
                        override fun onDone(utteranceId: String?) {
                            appContext.mainExecutor.execute {
                                try {
                                    val decoded = LocalSpeechPcm.decodeWaveToMonoPcm16(waveFile.readBytes())
                                    val target = LocalSpeechPcm.resampleLinear(
                                        decoded.monoSamples,
                                        decoded.sampleRate,
                                        TARGET_SAMPLE_RATE,
                                    )
                                    val raw = LocalSpeechPcm.toLittleEndianBytes(target)
                                    rawFile.writeBytes(raw)
                                    lines += "tts_wave_sample_rate=${decoded.sampleRate}"
                                    lines += "tts_wave_channels=${decoded.sourceChannelCount}"
                                    lines += "tts_wave_mono_samples=${decoded.monoSamples.size}"
                                    lines += "pcm16_16k_samples=${target.size}"
                                    lines += "pcm16_16k_bytes=${raw.size}"
                                    lines += "pcm16_16k_nonempty=${raw.isNotEmpty()}"
                                    try { tts.shutdown() } catch (_: Throwable) {}
                                    activeTts = null
                                    waveFile.delete()
                                    startRecognition(rawFile)
                                } catch (error: Throwable) {
                                    fail("pcm_prepare_${error.message ?: error.javaClass.simpleName}")
                                }
                            }
                        }

                        @Deprecated("Deprecated by framework")
                        override fun onError(utteranceId: String?) { fail("tts_synthesis_error_legacy") }
                        override fun onError(utteranceId: String?, errorCode: Int) { fail("tts_synthesis_error_$errorCode") }
                    })
                    val queued = tts.synthesizeToFile(TEST_TEXT, Bundle.EMPTY, waveFile, TTS_ID)
                    lines += "tts_synthesize_queue_result=$queued"
                    if (queued != TextToSpeech.SUCCESS) fail("tts_synthesis_queue_failed")
                }
            }
        }

        val supportRecognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        activeRecognizer = supportRecognizer
        supportRecognizer.checkRecognitionSupport(
            recognitionIntent(),
            appContext.mainExecutor,
            object : RecognitionSupportCallback {
                override fun onSupportResult(recognitionSupport: RecognitionSupport) {
                    val installed = recognitionSupport.installedOnDeviceLanguages.any(::isPolish)
                    val downloadable = recognitionSupport.supportedOnDeviceLanguages.any(::isPolish)
                    lines += "stt_pl_installed_before=$installed"
                    lines += "stt_pl_downloadable=$downloadable"
                    if (installed) {
                        supportRecognizer.destroy()
                        activeRecognizer = null
                        synthesizeAndRecognize()
                        return
                    }
                    if (!downloadable) {
                        fail("polish_model_not_downloadable")
                        return
                    }
                    lines += "model_download_requested=true"
                    supportRecognizer.triggerModelDownload(
                        recognitionIntent(),
                        appContext.mainExecutor,
                        object : ModelDownloadListener {
                            override fun onProgress(completedPercent: Int) {
                                lines += "model_download_progress=$completedPercent"
                            }

                            override fun onSuccess() {
                                lines += "model_download_success=true"
                                supportRecognizer.destroy()
                                activeRecognizer = null
                                synthesizeAndRecognize()
                            }

                            override fun onScheduled() {
                                lines += "model_download_scheduled=true"
                                lines += "loopback_success=false"
                                lines += "failure_reason=model_download_scheduled"
                                finish()
                            }

                            override fun onError(error: Int) {
                                fail("model_download_error_$error")
                            }
                        },
                    )
                }

                override fun onError(error: Int) { fail("support_check_error_$error") }
            },
        )
    }

    private fun isPolish(tag: String): Boolean = Locale.forLanguageTag(tag).language.equals("pl", ignoreCase = true)

    private fun normalize(value: String): String = value
        .lowercase(Locale.forLanguageTag(LANGUAGE_TAG))
        .replace(Regex("[^a-ząćęłńóśźż0-9 ]"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()

    private fun sanitize(value: String): String = value.replace('\n', ' ').replace('\r', ' ').replace('=', ':')
}
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    pcm_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechPcm.kt"
    pcm_path.parent.mkdir(parents=True, exist_ok=True)
    pcm_path.write_text(PCM, encoding="utf-8")

    test_path = ROOT / "app/src/test/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechPcmTest.kt"
    test_path.parent.mkdir(parents=True, exist_ok=True)
    test_path.write_text(TEST, encoding="utf-8")

    probe_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechPfdLoopbackProbe.kt"
    probe_path.write_text(PROBE, encoding="utf-8")

    activity_path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
    activity = activity_path.read_text(encoding="utf-8")
    activity = replace_once(
        activity,
        '    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE, false)) {\n',
        '''    private fun runRequestedProbe() {
        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PFD_LOOPBACK_PROBE, false)) {
            statusView.text = "Running local speech PFD loopback probe…"
            Log.i(TAG, "local_speech_pfd_loopback_probe_start=true")
            LocalSpeechPfdLoopbackProbe.run(this) { result ->
                runOnUiThread {
                    statusView.text = result
                    Log.i(TAG, "local_speech_pfd_loopback_probe_result:\\n$result")
                    finish()
                }
            }
            return
        }

        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE, false)) {
''',
        "local pfd probe dispatch",
    )
    activity = replace_once(
        activity,
        '        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n',
        '        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n        const val EXTRA_RUN_LOCAL_SPEECH_PFD_LOOPBACK_PROBE = "run_local_speech_pfd_loopback_probe"\n',
        "local pfd probe constant",
    )
    activity_path.write_text(activity, encoding="utf-8")
    print("local_speech_pfd_loopback_patch_applied=true")


if __name__ == "__main__":
    main()
