from pathlib import Path

ROOT = Path.cwd()
PROBE = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalPhoneLlmSpeechPipelineProbe.kt"
ACTIVITY = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"

PROBE.write_text(r'''package pl.michalmatu.aicallbridge

import android.content.Context
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
import pl.michalmatu.aicallbridge.localspeech.LocalTtsSpeechOutput
import pl.michalmatu.aicallbridge.textagent.CallTextAgentOutputApprovalPolicy
import pl.michalmatu.aicallbridge.textagent.LocalOpenAiCompatibleTextBackend
import pl.michalmatu.aicallbridge.textagent.LocalOpenAiTextBackendConfig
import java.io.File
import java.time.Instant
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call proof of local S22 STT -> phone-loopback LLM -> app approval -> local S22 TTS. */
internal object LocalPhoneLlmSpeechPipelineProbe {
    private const val USER_TEXT = "To jest test lokalnego modelu na telefonie."
    private const val REPORT_FILE = "local-phone-llm-speech-pipeline-report.txt"
    private const val TIMEOUT_MS = 120_000L

    fun run(context: Context, baseUrl: String, model: String, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val lines = mutableListOf(
            "probe=local_phone_llm_speech_pipeline",
            "call_required=false",
            "openai_api_used=false",
            "backend_location=phone_loopback",
            "approval_policy=application_owned",
            "timestamp_utc=${Instant.now()}",
            "target_pcm=mono,pcm16,${LocalSpeechFormat.SAMPLE_RATE_HZ}",
        )
        val finished = AtomicBoolean(false)
        val handler = Handler(Looper.getMainLooper())
        val sourceTts = LocalTtsSpeechOutput(appContext)
        val backend = try {
            LocalOpenAiCompatibleTextBackend(LocalOpenAiTextBackendConfig(baseUrl, model))
        } catch (error: Throwable) {
            val report = (lines + listOf(
                "backend_config_valid=false",
                "failure_reason=${sanitize(error.javaClass.simpleName)}",
                "probe_complete=true",
            )).joinToString("\n") + "\n"
            File(appContext.filesDir, REPORT_FILE).writeText(report)
            callback(report)
            return
        }
        lines += "backend_config_valid=true"
        val workflow = activeDiagnosticWorkflow()
        val approval = CallTextAgentOutputApprovalPolicy(
            workflow,
            CallCommitmentGate { "diagnostic-phone-llm-token" },
        )
        val pipeline = LocalSpeechTextPipeline(appContext, backend, approval)

        fun finish(success: Boolean, reason: String? = null) {
            if (!finished.compareAndSet(false, true)) return
            handler.removeCallbacksAndMessages(null)
            try { sourceTts.close() } catch (_: Throwable) {}
            try { pipeline.close() } catch (_: Throwable) {}
            lines += "local_phone_llm_speech_pipeline_success=$success"
            if (reason != null) lines += "failure_reason=${sanitize(reason)}"
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            File(appContext.filesDir, REPORT_FILE).writeText(report)
            callback(report)
        }

        handler.postDelayed({ finish(false, "probe_timeout") }, TIMEOUT_MS)
        sourceTts.synthesize(USER_TEXT, object : LocalTtsSpeechOutput.Listener {
            override fun onPcm16Mono16k(pcm: ByteArray) {
                lines += "source_tts_pcm_bytes=${pcm.size}"
                pipeline.start(object : LocalSpeechTextPipeline.Listener {
                    override fun onSpeechInputReady() {
                        lines += "stt_ready=true"
                        Thread({
                            try {
                                val silence = ByteArray(LocalSpeechFormat.bytesForDurationMs(500))
                                val chunk = LocalSpeechFormat.bytesForDurationMs(20)
                                fun writePaced(data: ByteArray): Boolean {
                                    var offset = 0
                                    while (offset < data.size && !finished.get()) {
                                        val length = minOf(chunk, data.size - offset)
                                        if (!pipeline.writeInputPcm(data, offset, length)) return false
                                        offset += length
                                        Thread.sleep(20L)
                                    }
                                    return true
                                }
                                if (!writePaced(silence) || !writePaced(pcm) || !writePaced(silence)) {
                                    appContext.mainExecutor.execute { finish(false, "pcm_write_failed") }
                                    return@Thread
                                }
                                pipeline.finishInput()
                                lines += "pcm_eof_sent=true"
                            } catch (error: Throwable) {
                                appContext.mainExecutor.execute { finish(false, "stream_${error.javaClass.simpleName}") }
                            }
                        }, "LocalPhoneLlmPipelineInput").start()
                    }

                    override fun onUserTranscript(text: String) {
                        lines += "stt_text=${sanitize(text)}"
                        lines += "stt_transcript_nonblank=${text.isNotBlank()}"
                    }

                    override fun onApprovedText(text: String) {
                        lines += "backend_complete_response=true"
                        lines += "approved_text=${sanitize(text)}"
                        lines += "approved_text_nonblank=${text.isNotBlank()}"
                    }

                    override fun onOutputPcm16Mono16k(pcm: ByteArray) {
                        lines += "output_tts_pcm_bytes=${pcm.size}"
                        val pcmOk = pcm.isNotEmpty()
                        lines += "approved_output_pcm_nonempty=$pcmOk"
                        val transcriptOk = lines.any { it == "stt_transcript_nonblank=true" }
                        val responseOk = lines.any { it == "approved_text_nonblank=true" }
                        finish(transcriptOk && responseOk && pcmOk)
                    }

                    override fun onDroppedText() = finish(false, "unexpected_output_drop")
                    override fun onError(reason: String) = finish(false, reason)
                })
            }

            override fun onError(reason: String) = finish(false, "source_tts_$reason")
        })
    }

    private fun activeDiagnosticWorkflow(): CallWorkflow {
        val task = CallTask(
            "diagnostic target",
            "diagnostic action",
            "diagnostic service",
            CallConstraints.unconstrained(),
            CallPreferences.none(),
            emptyMap(),
        )
        val workflow = CallWorkflow(task, CallConfirmationPolicy()) { }
        workflow.resolveTarget(CallResolvedTarget("diagnostic", "000"))
        workflow.markDialing()
        workflow.markCallActive()
        return workflow
    }

    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').replace('=', ':').take(240)
}
''')

s = ACTIVITY.read_text()
block = '''        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_PHONE_LLM_SPEECH_PIPELINE_PROBE, false)) {
            val baseUrl = intent.getStringExtra(EXTRA_LOCAL_TEXT_BASE_URL).orEmpty()
            val model = intent.getStringExtra(EXTRA_LOCAL_TEXT_MODEL).orEmpty()
            if (baseUrl.isBlank() || model.isBlank()) {
                finishWithError("local_phone_llm_pipeline_config_missing")
                return
            }
            statusView.text = "Running local phone LLM speech pipeline probe…"
            Log.i(TAG, "local_phone_llm_speech_pipeline_probe_start=true")
            LocalPhoneLlmSpeechPipelineProbe.run(this, baseUrl, model) { result ->
                runOnUiThread {
                    statusView.text = result
                    Log.i(TAG, "local_phone_llm_speech_pipeline_probe_result:\\n$result")
                    finish()
                }
            }
            return
        }

'''
anchor = "    private fun runRequestedProbe() {\n"
if "EXTRA_RUN_LOCAL_PHONE_LLM_SPEECH_PIPELINE_PROBE" not in s:
    if s.count(anchor) != 1:
        raise RuntimeError("runRequestedProbe anchor mismatch")
    s = s.replace(anchor, anchor + block, 1)
const_anchor = '        const val EXTRA_RUN_LOCAL_MAC_TEXT_BACKEND_PROBE = "run_local_mac_text_backend_probe"\n'
const_line = '        const val EXTRA_RUN_LOCAL_PHONE_LLM_SPEECH_PIPELINE_PROBE = "run_local_phone_llm_speech_pipeline_probe"\n'
if const_line not in s:
    if s.count(const_anchor) != 1:
        raise RuntimeError("constant anchor mismatch")
    s = s.replace(const_anchor, const_line + const_anchor, 1)
ACTIVITY.write_text(s)
print("local_phone_llm_full_pipeline_probe_written=true")
