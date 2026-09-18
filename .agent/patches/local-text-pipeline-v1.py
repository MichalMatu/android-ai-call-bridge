from pathlib import Path
import sys

ROOT = Path.cwd()

TEST = r'''package pl.michalmatu.aicallbridge.textagent

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import pl.michalmatu.aicallbridge.agent.CallCommitmentGate
import pl.michalmatu.aicallbridge.agent.CallConfirmationPolicy
import pl.michalmatu.aicallbridge.agent.CallConstraints
import pl.michalmatu.aicallbridge.agent.CallPreferences
import pl.michalmatu.aicallbridge.agent.CallProposal
import pl.michalmatu.aicallbridge.agent.CallResolvedTarget
import pl.michalmatu.aicallbridge.agent.CallTask
import pl.michalmatu.aicallbridge.agent.CallWorkflow

class TextCallTurnControllerTest {
    @Test
    fun completeBackendTextIsApprovedBeforeRelease() {
        val backend = FakeBackend()
        val order = mutableListOf<String>()
        val controller = TextCallTurnController(
            backend,
            TextOutputApprovalPolicy {
                order += "approval"
                TextOutputDecision.RELEASE
            },
        )
        var approved = ""

        controller.submitUserText("dzień dobry", object : TextCallTurnController.Listener {
            override fun onApprovedResponse(text: String) {
                order += "approved"
                approved = text
            }

            override fun onDroppedResponse() = error("unexpected drop")
            override fun onError(reason: String) = error(reason)
        })
        order += "backend_complete"
        backend.complete("gotowa odpowiedź")

        assertEquals("gotowa odpowiedź", approved)
        assertEquals(listOf("backend_complete", "approval", "approved"), order)
    }

    @Test
    fun droppedTextNeverBecomesApprovedOutput() {
        val backend = FakeBackend()
        val controller = TextCallTurnController(
            backend,
            TextOutputApprovalPolicy { TextOutputDecision.DROP },
        )
        var dropped = false
        var approved = false

        controller.submitUserText("test", object : TextCallTurnController.Listener {
            override fun onApprovedResponse(text: String) { approved = true }
            override fun onDroppedResponse() { dropped = true }
            override fun onError(reason: String) = error(reason)
        })
        backend.complete("nie wolno tego wypowiedzieć")

        assertTrue(dropped)
        assertFalse(approved)
    }

    @Test
    fun staleBackendCompletionAfterCancelIsIgnored() {
        val backend = FakeBackend()
        val controller = TextCallTurnController(
            backend,
            TextOutputApprovalPolicy { TextOutputDecision.RELEASE },
        )
        var callbackCount = 0

        controller.submitUserText("test", object : TextCallTurnController.Listener {
            override fun onApprovedResponse(text: String) { callbackCount += 1 }
            override fun onDroppedResponse() { callbackCount += 1 }
            override fun onError(reason: String) { callbackCount += 1 }
        })
        controller.cancel()
        backend.complete("spóźniona odpowiedź")

        assertEquals(0, callbackCount)
        assertTrue(backend.cancelCount >= 1)
    }

    @Test
    fun applicationPolicyRequiresActiveNegotiationAndNoCommitmentPermit() {
        val inactiveWorkflow = workflow(active = false)
        val inactiveGate = CallCommitmentGate { "inactive-token" }
        val inactivePolicy = CallTextAgentOutputApprovalPolicy(inactiveWorkflow, inactiveGate)
        assertEquals(TextOutputDecision.DROP, inactivePolicy.evaluate("tekst"))

        val activeWorkflow = workflow(active = true)
        val activeGate = CallCommitmentGate { "active-token" }
        val activePolicy = CallTextAgentOutputApprovalPolicy(activeWorkflow, activeGate)
        assertEquals(TextOutputDecision.RELEASE, activePolicy.evaluate("tekst"))

        activeGate.authorize(CallProposal(null, null, null, null, null))
        assertEquals(TextOutputDecision.DROP, activePolicy.evaluate("tekst"))
    }

    private fun workflow(active: Boolean): CallWorkflow {
        val task = CallTask(
            "diagnostic target",
            "diagnostic action",
            "diagnostic service",
            CallConstraints.unconstrained(),
            CallPreferences.none(),
            emptyMap(),
        )
        val workflow = CallWorkflow(task, CallConfirmationPolicy()) { }
        if (active) {
            workflow.resolveTarget(CallResolvedTarget("diagnostic", "000"))
            workflow.markDialing()
            workflow.markCallActive()
        }
        return workflow
    }

    private class FakeBackend : TextCallAgentBackend {
        private var listener: TextCallAgentBackend.Listener? = null
        var cancelCount: Int = 0
            private set

        override fun generate(userText: String, listener: TextCallAgentBackend.Listener) {
            this.listener = listener
        }

        fun complete(text: String) {
            listener?.onComplete(text)
        }

        override fun cancel() {
            cancelCount += 1
        }
    }
}
'''

BACKEND = r'''package pl.michalmatu.aicallbridge.textagent

/** Complete-text provider boundary shared by OpenAI text and future local Mac LLM backends. */
internal interface TextCallAgentBackend : AutoCloseable {
    interface Listener {
        fun onComplete(text: String)
        fun onError(reason: String)
    }

    fun generate(userText: String, listener: Listener)

    fun cancel()

    override fun close() = cancel()
}
'''

APPROVAL = r'''package pl.michalmatu.aicallbridge.textagent

import pl.michalmatu.aicallbridge.agent.CallCommitmentGate
import pl.michalmatu.aicallbridge.agent.CallWorkflow
import pl.michalmatu.aicallbridge.agent.CallWorkflowState

enum class TextOutputDecision {
    RELEASE,
    DROP,
}

fun interface TextOutputApprovalPolicy {
    fun evaluate(text: String): TextOutputDecision
}

/** Application-owned speech release gate for complete text-agent responses. */
internal class CallTextAgentOutputApprovalPolicy(
    private val workflow: CallWorkflow,
    private val commitmentGate: CallCommitmentGate,
) : TextOutputApprovalPolicy {
    override fun evaluate(text: String): TextOutputDecision {
        if (text.isBlank()) return TextOutputDecision.DROP
        val safeToRelease =
            workflow.snapshot().state() == CallWorkflowState.ACTIVE_NEGOTIATION &&
                !commitmentGate.hasAuthorization()
        return if (safeToRelease) TextOutputDecision.RELEASE else TextOutputDecision.DROP
    }
}
'''

CONTROLLER = r'''package pl.michalmatu.aicallbridge.textagent

import pl.michalmatu.aicallbridge.localspeech.LocalSpeechGenerationGate

/**
 * One conservative text turn: FINAL ASR text -> COMPLETE backend text -> app approval.
 * Partial backend output is intentionally not part of this contract.
 */
internal class TextCallTurnController(
    private val backend: TextCallAgentBackend,
    private val approvalPolicy: TextOutputApprovalPolicy,
) : AutoCloseable {
    interface Listener {
        fun onApprovedResponse(text: String)
        fun onDroppedResponse()
        fun onError(reason: String)
    }

    private val gate = LocalSpeechGenerationGate()

    fun submitUserText(userText: String, listener: Listener) {
        require(userText.isNotBlank()) { "user_text_must_not_be_blank" }
        backend.cancel()
        val generation = gate.begin()
        try {
            backend.generate(userText, object : TextCallAgentBackend.Listener {
                override fun onComplete(text: String) {
                    if (!gate.isCurrent(generation)) return
                    if (text.isBlank()) {
                        finishError(generation, listener, "backend_empty_response")
                        return
                    }
                    when (approvalPolicy.evaluate(text)) {
                        TextOutputDecision.RELEASE -> {
                            finishGeneration(generation)
                            listener.onApprovedResponse(text)
                        }
                        TextOutputDecision.DROP -> {
                            finishGeneration(generation)
                            listener.onDroppedResponse()
                        }
                    }
                }

                override fun onError(reason: String) {
                    finishError(generation, listener, "backend_${sanitize(reason)}")
                }
            })
        } catch (error: Throwable) {
            finishError(generation, listener, "backend_start_${error.javaClass.simpleName}")
        }
    }

    fun cancel() {
        gate.invalidate()
        backend.cancel()
    }

    override fun close() {
        cancel()
        try { backend.close() } catch (_: Throwable) {}
    }

    private fun finishError(generation: Long, listener: Listener, reason: String) {
        if (!gate.isCurrent(generation)) return
        finishGeneration(generation)
        listener.onError(reason)
    }

    private fun finishGeneration(generation: Long) {
        if (!gate.isCurrent(generation)) return
        gate.invalidate()
        backend.cancel()
    }

    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').take(160)
}
'''

PIPELINE = r'''package pl.michalmatu.aicallbridge.localspeech

import android.content.Context
import pl.michalmatu.aicallbridge.textagent.TextCallAgentBackend
import pl.michalmatu.aicallbridge.textagent.TextCallTurnController
import pl.michalmatu.aicallbridge.textagent.TextOutputApprovalPolicy

/**
 * One conservative LOCAL_STT_TTS turn. It never emits PCM until the complete backend response has
 * passed the application-owned text approval policy.
 */
internal class LocalSpeechTextPipeline(
    context: Context,
    backend: TextCallAgentBackend,
    approvalPolicy: TextOutputApprovalPolicy,
    languageTag: String = "pl-PL",
) : AutoCloseable {
    interface Listener {
        fun onSpeechInputReady()
        fun onUserTranscript(text: String)
        fun onApprovedText(text: String)
        fun onOutputPcm16Mono16k(pcm: ByteArray)
        fun onDroppedText()
        fun onError(reason: String)
    }

    private val input = OnDeviceSpeechInput(context, languageTag)
    private val output = LocalTtsSpeechOutput(context, languageTag)
    private val controller = TextCallTurnController(backend, approvalPolicy)
    private val gate = LocalSpeechGenerationGate()

    fun start(listener: Listener) {
        cancel()
        val generation = gate.begin()
        input.start(object : OnDeviceSpeechInput.Listener {
            override fun onReady() {
                if (gate.isCurrent(generation)) listener.onSpeechInputReady()
            }

            override fun onFinalTranscript(text: String) {
                if (!gate.isCurrent(generation)) return
                listener.onUserTranscript(text)
                controller.submitUserText(text, object : TextCallTurnController.Listener {
                    override fun onApprovedResponse(text: String) {
                        if (!gate.isCurrent(generation)) return
                        listener.onApprovedText(text)
                        output.synthesize(text, object : LocalTtsSpeechOutput.Listener {
                            override fun onPcm16Mono16k(pcm: ByteArray) {
                                if (!gate.isCurrent(generation)) return
                                finishGeneration(generation)
                                listener.onOutputPcm16Mono16k(pcm)
                            }

                            override fun onError(reason: String) {
                                finishError(generation, listener, "tts_$reason")
                            }
                        })
                    }

                    override fun onDroppedResponse() {
                        if (!gate.isCurrent(generation)) return
                        finishGeneration(generation)
                        listener.onDroppedText()
                    }

                    override fun onError(reason: String) {
                        finishError(generation, listener, reason)
                    }
                })
            }

            override fun onError(reason: String) {
                finishError(generation, listener, "stt_$reason")
            }
        })
    }

    fun writeInputPcm(bytes: ByteArray, offset: Int = 0, length: Int = bytes.size): Boolean =
        input.writePcm(bytes, offset, length)

    fun finishInput() = input.finishInput()

    fun cancel() {
        gate.invalidate()
        input.cancel()
        controller.cancel()
        output.cancel()
    }

    override fun close() {
        cancel()
        controller.close()
        input.close()
        output.close()
    }

    private fun finishError(generation: Long, listener: Listener, reason: String) {
        if (!gate.isCurrent(generation)) return
        finishGeneration(generation)
        listener.onError(reason)
    }

    private fun finishGeneration(generation: Long) {
        if (!gate.isCurrent(generation)) return
        gate.invalidate()
        input.cancel()
        controller.cancel()
        output.cancel()
    }
}
'''

PROBE = r'''package pl.michalmatu.aicallbridge

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
import pl.michalmatu.aicallbridge.textagent.TextCallAgentBackend
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call proof of FINAL STT -> complete text backend -> app approval -> local TTS. */
object LocalSpeechTextPipelineProbe {
    private const val USER_TEXT = "To jest test lokalnego agenta tekstowego."
    private const val RESPONSE_TEXT = "Lokalny agent tekstowy działa poprawnie."
    private const val REPORT_FILE = "local-speech-text-pipeline-report.txt"
    private const val TIMEOUT_MS = 40_000L

    fun run(context: Context, callback: (String) -> Unit) {
        val appContext = context.applicationContext
        val lines = mutableListOf<String>()
        val finished = AtomicBoolean(false)
        val handler = Handler(Looper.getMainLooper())
        val sourceTts = LocalTtsSpeechOutput(appContext)
        val backend = DeterministicBackend(appContext)
        val workflow = activeDiagnosticWorkflow()
        val commitmentGate = CallCommitmentGate { "diagnostic-text-token" }
        val approval = CallTextAgentOutputApprovalPolicy(workflow, commitmentGate)
        val pipeline = LocalSpeechTextPipeline(appContext, backend, approval)

        fun finish(success: Boolean, reason: String? = null) {
            if (!finished.compareAndSet(false, true)) return
            handler.removeCallbacksAndMessages(null)
            try { sourceTts.close() } catch (_: Throwable) {}
            try { pipeline.close() } catch (_: Throwable) {}
            lines += "text_pipeline_success=$success"
            if (reason != null) lines += "failure_reason=${sanitize(reason)}"
            lines += "probe_complete=true"
            val report = lines.joinToString("\n") + "\n"
            File(appContext.filesDir, REPORT_FILE).writeText(report)
            callback(report)
        }

        lines += "probe_version=1"
        lines += "timestamp_utc=${Instant.now()}"
        lines += "target_pcm=mono,pcm16,${LocalSpeechFormat.SAMPLE_RATE_HZ}"
        lines += "approval_policy=application_owned"
        lines += "backend_mode=deterministic_complete_text"
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
                                appContext.mainExecutor.execute {
                                    finish(false, "stream_${error.javaClass.simpleName}")
                                }
                            }
                        }, "LocalTextPipelineInput").start()
                    }

                    override fun onUserTranscript(text: String) {
                        lines += "stt_text=${sanitize(text)}"
                    }

                    override fun onApprovedText(text: String) {
                        lines += "approved_text=${sanitize(text)}"
                    }

                    override fun onOutputPcm16Mono16k(pcm: ByteArray) {
                        lines += "output_tts_pcm_bytes=${pcm.size}"
                        val transcriptOk = normalize(backend.lastUserText).contains("lokalnego agenta tekstowego")
                        val responseOk = backend.lastResponse == RESPONSE_TEXT
                        val pcmOk = pcm.isNotEmpty()
                        lines += "backend_received_transcript=$transcriptOk"
                        lines += "backend_complete_response=$responseOk"
                        lines += "approved_output_pcm_nonempty=$pcmOk"
                        finish(transcriptOk && responseOk && pcmOk)
                    }

                    override fun onDroppedText() {
                        finish(false, "unexpected_output_drop")
                    }

                    override fun onError(reason: String) {
                        finish(false, reason)
                    }
                })
            }

            override fun onError(reason: String) {
                finish(false, "source_tts_$reason")
            }
        })
    }

    private class DeterministicBackend(
        private val context: Context,
    ) : TextCallAgentBackend {
        @Volatile
        var lastUserText: String = ""
            private set
        @Volatile
        var lastResponse: String = ""
            private set
        @Volatile
        private var generation = 0L

        @Synchronized
        override fun generate(userText: String, listener: TextCallAgentBackend.Listener) {
            generation += 1L
            val current = generation
            lastUserText = userText
            context.mainExecutor.execute {
                synchronized(this) {
                    if (generation != current) return@execute
                    lastResponse = RESPONSE_TEXT
                }
                listener.onComplete(RESPONSE_TEXT)
            }
        }

        @Synchronized
        override fun cancel() {
            generation += 1L
        }
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

    private fun normalize(value: String): String = value
        .lowercase(Locale.forLanguageTag("pl-PL"))
        .replace(Regex("[^a-ząćęłńóśźż0-9 ]"), " ")
        .replace(Regex("\\s+"), " ")
        .trim()

    private fun sanitize(value: String): String =
        value.replace('\n', ' ').replace('\r', ' ').replace('=', ':').take(240)
}
'''


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def patch_activity() -> None:
    path = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
    text = path.read_text(encoding="utf-8")
    anchor = '''    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE, false)) {'''
    inserted = '''    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_TEXT_PIPELINE_PROBE, false)) {\n            statusView.text = "Running local speech + text pipeline probe…"\n            Log.i(TAG, "local_speech_text_pipeline_probe_start=true")\n            LocalSpeechTextPipelineProbe.run(this) { result ->\n                runOnUiThread {\n                    statusView.text = result\n                    Log.i(TAG, "local_speech_text_pipeline_probe_result:\\n$result")\n                    finish()\n                }\n            }\n            return\n        }\n\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE, false)) {'''
    if text.count(anchor) != 1:
        raise RuntimeError(f"activity runRequestedProbe anchor count={text.count(anchor)}")
    text = text.replace(anchor, inserted, 1)
    const_anchor = '''        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n        const val EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE = "run_local_speech_production_probe"'''
    const_insert = '''        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n        const val EXTRA_RUN_LOCAL_SPEECH_TEXT_PIPELINE_PROBE = "run_local_speech_text_pipeline_probe"\n        const val EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE = "run_local_speech_production_probe"'''
    if text.count(const_anchor) != 1:
        raise RuntimeError(f"activity constant anchor count={text.count(const_anchor)}")
    path.write_text(text.replace(const_anchor, const_insert, 1), encoding="utf-8")

mode = sys.argv[1] if len(sys.argv) > 1 else "green"
if mode == "red":
    write("app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/TextCallTurnControllerTest.kt", TEST)
    print("local_text_pipeline_red_written=true")
elif mode == "green":
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/TextCallAgentBackend.kt", BACKEND)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/TextOutputApprovalPolicy.kt", APPROVAL)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/TextCallTurnController.kt", CONTROLLER)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/LocalSpeechTextPipeline.kt", PIPELINE)
    write("app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechTextPipelineProbe.kt", PROBE)
    patch_activity()
    print("local_text_pipeline_green_written=true")
else:
    raise SystemExit(f"unknown mode: {mode}")
