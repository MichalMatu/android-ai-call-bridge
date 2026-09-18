from pathlib import Path

ROOT = Path.cwd()
PATH = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechPfdLoopbackProbe.kt"
text = PATH.read_text(encoding="utf-8")

old_vars = '''        var activeRecognizer: SpeechRecognizer? = null
        var activePfd: ParcelFileDescriptor? = null
        var activeTts: TextToSpeech? = null
'''
new_vars = '''        var activeRecognizer: SpeechRecognizer? = null
        var activePfd: ParcelFileDescriptor? = null
        var activeWriterPfd: ParcelFileDescriptor? = null
        var activeTts: TextToSpeech? = null
        val recognizedSegments = mutableListOf<String>()
'''
if text.count(old_vars) != 1:
    raise SystemExit("active vars anchor mismatch")
text = text.replace(old_vars, new_vars, 1)

old_cleanup = '''            try { activeRecognizer?.destroy() } catch (_: Throwable) {}
            try { activePfd?.close() } catch (_: Throwable) {}
            try { activeTts?.shutdown() } catch (_: Throwable) {}
'''
new_cleanup = '''            try { activeRecognizer?.destroy() } catch (_: Throwable) {}
            try { activeWriterPfd?.close() } catch (_: Throwable) {}
            try { activePfd?.close() } catch (_: Throwable) {}
            try { activeTts?.shutdown() } catch (_: Throwable) {}
'''
if text.count(old_cleanup) != 1:
    raise SystemExit("cleanup anchor mismatch")
text = text.replace(old_cleanup, new_cleanup, 1)

start = text.index("        fun startRecognition(rawFile: File) {")
end = text.index("\n        fun synthesizeAndRecognize() {", start)
new_fn = r'''        fun startRecognition(rawFile: File) {
            val recognizer = SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
            activeRecognizer = recognizer
            val pipe = ParcelFileDescriptor.createPipe()
            val readPfd = pipe[0]
            val writePfd = pipe[1]
            activePfd = readPfd
            activeWriterPfd = writePfd
            val request = recognitionIntent().apply {
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE, readPfd)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_CHANNEL_COUNT, 1)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_ENCODING, AudioFormat.ENCODING_PCM_16BIT)
                putExtra(RecognizerIntent.EXTRA_AUDIO_SOURCE_SAMPLING_RATE, TARGET_SAMPLE_RATE)
                putExtra(RecognizerIntent.EXTRA_SEGMENTED_SESSION, RecognizerIntent.EXTRA_AUDIO_SOURCE)
            }

            fun transcriptSuccess(value: String): Boolean {
                val normalized = normalize(value)
                return normalized.contains("test") &&
                    normalized.contains("lokal") &&
                    normalized.contains("rozpozn")
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

                override fun onSegmentResults(segmentResults: Bundle) {
                    val hypotheses = segmentResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                    val top = hypotheses.firstOrNull().orEmpty()
                    lines += "stt_segment_result_count=${hypotheses.size}"
                    lines += "stt_segment_top=${sanitize(top)}"
                    if (top.isNotBlank()) recognizedSegments += top
                }

                override fun onEndOfSegmentedSession() {
                    lines += "stt_segmented_session_end=true"
                    val transcript = recognizedSegments.joinToString(" ")
                    lines += "stt_top=${sanitize(transcript)}"
                    val success = transcriptSuccess(transcript)
                    lines += "loopback_success=$success"
                    if (!success) lines += "failure_reason=unexpected_transcript"
                    finish()
                }

                override fun onResults(results: Bundle?) {
                    val hypotheses = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION).orEmpty()
                    val top = hypotheses.firstOrNull().orEmpty()
                    lines += "stt_result_count=${hypotheses.size}"
                    lines += "stt_top=${sanitize(top)}"
                    val success = transcriptSuccess(top)
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
                return
            }

            val raw = rawFile.readBytes()
            Thread({
                try {
                    ParcelFileDescriptor.AutoCloseOutputStream(writePfd).use { output ->
                        val chunkBytes = TARGET_SAMPLE_RATE * 2 * 20 / 1000
                        val silence = ByteArray(TARGET_SAMPLE_RATE * 2 / 2)

                        fun writePaced(data: ByteArray) {
                            var offset = 0
                            while (offset < data.size && !finished.get()) {
                                val size = minOf(chunkBytes, data.size - offset)
                                output.write(data, offset, size)
                                output.flush()
                                offset += size
                                Thread.sleep(20)
                            }
                        }

                        writePaced(silence)
                        writePaced(raw)
                        writePaced(silence)
                    }
                    activeWriterPfd = null
                } catch (error: Throwable) {
                    appContext.mainExecutor.execute {
                        if (!finished.get()) fail("pcm_pipe_${error.javaClass.simpleName}")
                    }
                }
            }, "LocalSpeechPcmPipe").start()
        }
'''
text = text[:start] + new_fn + text[end:]
PATH.write_text(text, encoding="utf-8")
print("local_speech_pfd_pipe_fix_applied=true")
