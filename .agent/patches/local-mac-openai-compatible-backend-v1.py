from pathlib import Path

ROOT = Path.cwd()
BUILD = ROOT / "app/build.gradle.kts"
TEST = ROOT / "app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/LocalOpenAiCompatibleTextBackendTest.kt"
BACKEND = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/LocalOpenAiCompatibleTextBackend.kt"
PROBE = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalMacTextBackendProbe.kt"
ACTIVITY = ROOT / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"
DEBUG_MANIFEST = ROOT / "app/src/debug/AndroidManifest.xml"

TEST_TEXT = r'''package pl.michalmatu.aicallbridge.textagent

import java.io.BufferedInputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.nio.charset.StandardCharsets
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class LocalOpenAiCompatibleTextBackendTest {
    @Test
    fun `sends one non-streaming chat completion and returns complete text`() {
        OneShotHttpServer(
            statusCode = 200,
            responseBody = """{"choices":[{"message":{"content":"Odpowiedź lokalna."}}]}""",
        ).use { server ->
            val backend = LocalOpenAiCompatibleTextBackend(
                LocalOpenAiTextBackendConfig(
                    baseUrl = server.baseUrl(),
                    model = "fixture-model",
                ),
            )
            val latch = CountDownLatch(1)
            var result: String? = null
            var error: String? = null
            backend.generate("Cześć", object : TextCallAgentBackend.Listener {
                override fun onComplete(text: String) {
                    result = text
                    latch.countDown()
                }

                override fun onError(reason: String) {
                    error = reason
                    latch.countDown()
                }
            })

            assertTrue(latch.await(5, TimeUnit.SECONDS))
            assertEquals("Odpowiedź lokalna.", result)
            assertNull(error)
            val request = server.awaitRequest()
            assertTrue(request.startsWith("POST /v1/chat/completions HTTP/1.1"))
            assertTrue(request.contains("\"model\":\"fixture-model\""))
            assertTrue(request.contains("\"stream\":false"))
            assertTrue(request.contains("\"role\":\"user\""))
            assertTrue(request.contains("Cześć"))
            backend.close()
        }
    }

    @Test
    fun `reports http failure without exposing response body`() {
        OneShotHttpServer(statusCode = 503, responseBody = "SECRET BODY").use { server ->
            val backend = LocalOpenAiCompatibleTextBackend(
                LocalOpenAiTextBackendConfig(server.baseUrl(), "fixture-model"),
            )
            val latch = CountDownLatch(1)
            var error: String? = null
            backend.generate("test", object : TextCallAgentBackend.Listener {
                override fun onComplete(text: String) = latch.countDown()
                override fun onError(reason: String) {
                    error = reason
                    latch.countDown()
                }
            })
            assertTrue(latch.await(5, TimeUnit.SECONDS))
            assertEquals("http_503", error)
            assertTrue(error?.contains("SECRET") == false)
            backend.close()
        }
    }

    @Test
    fun `rejects public cleartext endpoint`() {
        try {
            LocalOpenAiTextBackendConfig("http://example.com:11434/v1/", "fixture-model")
            fail("public cleartext endpoint must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message.orEmpty().contains("local", ignoreCase = true))
        }
    }

    @Test
    fun `rejects standard OpenAI api key shaped token`() {
        try {
            LocalOpenAiTextBackendConfig(
                "https://localhost:11434/v1/",
                "fixture-model",
                "sk-should-never-live-on-device",
            )
            fail("standard OpenAI key shaped token must be rejected")
        } catch (expected: IllegalArgumentException) {
            assertTrue(expected.message.orEmpty().contains("OpenAI", ignoreCase = true))
        }
    }

    private class OneShotHttpServer(
        private val statusCode: Int,
        private val responseBody: String,
    ) : AutoCloseable {
        private val socket = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        private val executor = Executors.newSingleThreadExecutor()
        private val requestLatch = CountDownLatch(1)
        @Volatile private var requestText: String = ""

        init {
            executor.submit {
                socket.accept().use { client ->
                    client.soTimeout = 5_000
                    val input = BufferedInputStream(client.getInputStream())
                    val headerBytes = ArrayList<Byte>()
                    var matched = 0
                    val terminator = byteArrayOf(13, 10, 13, 10)
                    while (matched < terminator.size) {
                        val value = input.read()
                        if (value < 0) break
                        val byte = value.toByte()
                        headerBytes += byte
                        matched = if (byte == terminator[matched]) matched + 1 else if (byte == terminator[0]) 1 else 0
                    }
                    val headers = headerBytes.toByteArray().toString(StandardCharsets.UTF_8)
                    val contentLength = Regex("(?i)Content-Length:\\s*(\\d+)")
                        .find(headers)
                        ?.groupValues
                        ?.get(1)
                        ?.toInt()
                        ?: 0
                    val body = ByteArray(contentLength)
                    var offset = 0
                    while (offset < body.size) {
                        val read = input.read(body, offset, body.size - offset)
                        if (read < 0) break
                        offset += read
                    }
                    requestText = headers + body.copyOf(offset).toString(StandardCharsets.UTF_8)
                    requestLatch.countDown()

                    val payload = responseBody.toByteArray(StandardCharsets.UTF_8)
                    val reason = if (statusCode == 200) "OK" else "Service Unavailable"
                    val responseHeaders = buildString {
                        append("HTTP/1.1 $statusCode $reason\\r\\n")
                        append("Content-Type: application/json\\r\\n")
                        append("Content-Length: ${payload.size}\\r\\n")
                        append("Connection: close\\r\\n\\r\\n")
                    }.toByteArray(StandardCharsets.US_ASCII)
                    client.getOutputStream().apply {
                        write(responseHeaders)
                        write(payload)
                        flush()
                    }
                }
            }
        }

        fun baseUrl(): String = "http://127.0.0.1:${socket.localPort}/v1/"

        fun awaitRequest(): String {
            assertTrue(requestLatch.await(5, TimeUnit.SECONDS))
            return requestText
        }

        override fun close() {
            try { socket.close() } catch (_: Throwable) {}
            executor.shutdownNow()
        }
    }
}
'''

BACKEND_TEXT = r'''package pl.michalmatu.aicallbridge.textagent

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.IOException
import java.util.concurrent.TimeUnit
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

/** Configuration for a local, OpenAI-compatible text endpoint such as Ollama on the user's Mac. */
internal class LocalOpenAiTextBackendConfig(
    baseUrl: String,
    model: String,
    bearerToken: String? = null,
) {
    val model: String = model.trim()
    val bearerToken: String? = bearerToken?.trim()?.takeIf { it.isNotEmpty() }
    val chatCompletionsUrl: HttpUrl

    init {
        require(this.model.isNotEmpty()) { "local text model must not be blank" }
        require(this.model.length <= MAX_MODEL_CHARS) { "local text model is too long" }
        if (this.bearerToken != null) {
            require(this.bearerToken.length <= MAX_TOKEN_CHARS) { "local text bearer token is too long" }
            require(!STANDARD_OPENAI_KEY.matches(this.bearerToken)) {
                "standard OpenAI API keys must never be stored in the local Mac backend config"
            }
        }

        val parsed = baseUrl.trim().toHttpUrlOrNull()
            ?: throw IllegalArgumentException("local text endpoint URL is invalid")
        require(parsed.scheme == "http" || parsed.scheme == "https") {
            "local text endpoint must use http or https"
        }
        require(parsed.username.isEmpty() && parsed.password.isEmpty()) {
            "local text endpoint URL must not contain user info"
        }
        require(parsed.query == null && parsed.fragment == null) {
            "local text endpoint URL must not contain query or fragment"
        }
        require(isLocalHost(parsed.host)) {
            "local text endpoint host must be loopback, RFC1918, link-local, Tailscale CGNAT, or .local"
        }
        chatCompletionsUrl = parsed.newBuilder()
            .encodedPath("/v1/chat/completions")
            .query(null)
            .fragment(null)
            .build()
    }

    private companion object {
        const val MAX_MODEL_CHARS = 160
        const val MAX_TOKEN_CHARS = 512
        val STANDARD_OPENAI_KEY = Regex("(?i)sk-[A-Za-z0-9_-]{8,}")

        fun isLocalHost(host: String): Boolean {
            val value = host.lowercase()
            if (value == "localhost" || value.endsWith(".local")) return true
            if (value == "::1" || value.startsWith("fe80:") || value.startsWith("fc") || value.startsWith("fd")) {
                return true
            }
            val parts = value.split('.')
            if (parts.size != 4) return false
            val octets = parts.map { it.toIntOrNull() ?: return false }
            if (octets.any { it !in 0..255 }) return false
            return when {
                octets[0] == 10 -> true
                octets[0] == 127 -> true
                octets[0] == 169 && octets[1] == 254 -> true
                octets[0] == 172 && octets[1] in 16..31 -> true
                octets[0] == 192 && octets[1] == 168 -> true
                octets[0] == 100 && octets[1] in 64..127 -> true
                else -> false
            }
        }
    }
}

/** Complete-response adapter for a local OpenAI-compatible `/v1/chat/completions` endpoint. */
internal class LocalOpenAiCompatibleTextBackend(
    private val config: LocalOpenAiTextBackendConfig,
    private val callFactory: Call.Factory = defaultClient(),
) : TextCallAgentBackend {
    private val lock = Any()
    private var activeCall: Call? = null

    override fun generate(userText: String, listener: TextCallAgentBackend.Listener) {
        require(userText.isNotBlank()) { "user_text_must_not_be_blank" }
        cancel()
        val request = Request.Builder()
            .url(config.chatCompletionsUrl)
            .post(requestJson(userText).toRequestBody(JSON_MEDIA_TYPE))
            .apply {
                config.bearerToken?.let { header("Authorization", "Bearer $it") }
            }
            .build()
        val call = callFactory.newCall(request)
        synchronized(lock) { activeCall = call }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (call.isCanceled()) return
                if (!claim(call)) return
                listener.onError("network_${e.javaClass.simpleName}")
            }

            override fun onResponse(call: Call, response: Response) {
                response.use {
                    if (!claim(call)) return
                    if (!response.isSuccessful) {
                        listener.onError("http_${response.code}")
                        return
                    }
                    val body = try {
                        response.body.string()
                    } catch (_: IOException) {
                        listener.onError("response_read_failed")
                        return
                    }
                    if (body.length > MAX_RESPONSE_CHARS) {
                        listener.onError("response_too_large")
                        return
                    }
                    val text = parseCompleteText(body)
                    if (text == null) {
                        listener.onError("invalid_response")
                    } else {
                        listener.onComplete(text)
                    }
                }
            }
        })
    }

    override fun cancel() {
        val call = synchronized(lock) {
            val value = activeCall
            activeCall = null
            value
        }
        call?.cancel()
    }

    private fun claim(call: Call): Boolean = synchronized(lock) {
        if (activeCall !== call) return@synchronized false
        activeCall = null
        true
    }

    private fun requestJson(userText: String): String {
        val root = JsonObject().apply {
            addProperty("model", config.model)
            addProperty("stream", false)
            add("messages", com.google.gson.JsonArray().apply {
                add(JsonObject().apply {
                    addProperty("role", "user")
                    addProperty("content", userText)
                })
            })
        }
        return root.toString()
    }

    private fun parseCompleteText(body: String): String? {
        if (body.isBlank()) return null
        val root = try {
            JsonParser.parseString(body).takeIf { it.isJsonObject }?.asJsonObject
        } catch (_: RuntimeException) {
            null
        } ?: return null
        val choices = root.getAsJsonArray("choices") ?: return null
        if (choices.size() == 0) return null
        val first = choices[0].takeIf { it.isJsonObject }?.asJsonObject ?: return null
        val message = first.getAsJsonObject("message") ?: return null
        val content = message.get("content") ?: return null
        if (!content.isJsonPrimitive || !content.asJsonPrimitive.isString) return null
        return content.asString.trim().takeIf { it.isNotEmpty() }
    }

    private companion object {
        const val MAX_RESPONSE_CHARS = 64 * 1024
        val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(70, TimeUnit.SECONDS)
            .build()
    }
}
'''

PROBE_TEXT = r'''package pl.michalmatu.aicallbridge

import android.content.Context
import pl.michalmatu.aicallbridge.localspeech.LocalTtsSpeechOutput
import pl.michalmatu.aicallbridge.textagent.LocalOpenAiCompatibleTextBackend
import pl.michalmatu.aicallbridge.textagent.LocalOpenAiTextBackendConfig
import pl.michalmatu.aicallbridge.textagent.TextCallTurnController
import pl.michalmatu.aicallbridge.textagent.TextOutputApprovalPolicy
import pl.michalmatu.aicallbridge.textagent.TextOutputDecision
import java.util.concurrent.atomic.AtomicBoolean

/** Off-call physical probe for S22 -> local Mac OpenAI-compatible text backend -> local S22 TTS. */
internal object LocalMacTextBackendProbe {
    private const val REPORT_FILE = "local-mac-text-backend-report.txt"

    fun run(
        context: Context,
        baseUrl: String,
        model: String,
        callback: (String) -> Unit,
    ) {
        val appContext = context.applicationContext
        val lines = mutableListOf(
            "probe=local_mac_text_backend",
            "call_required=false",
            "openai_api_used=false",
        )
        val finished = AtomicBoolean(false)
        val backend = try {
            LocalOpenAiCompatibleTextBackend(LocalOpenAiTextBackendConfig(baseUrl, model))
        } catch (error: Throwable) {
            val result = (lines + listOf(
                "backend_config_valid=false",
                "failure=${error.javaClass.simpleName}",
                "probe_complete=true",
            )).joinToString("\n")
            writeReport(appContext, result)
            callback(result)
            return
        }
        lines += "backend_config_valid=true"
        val controller = TextCallTurnController(
            backend,
            TextOutputApprovalPolicy { TextOutputDecision.RELEASE },
        )
        val tts = LocalTtsSpeechOutput(appContext)

        fun finish(success: Boolean, reason: String? = null) {
            if (!finished.compareAndSet(false, true)) return
            if (reason != null) lines += "failure=$reason"
            lines += "local_mac_backend_success=$success"
            lines += "probe_complete=true"
            val result = lines.joinToString("\n")
            try { controller.close() } catch (_: Throwable) {}
            try { tts.close() } catch (_: Throwable) {}
            writeReport(appContext, result)
            callback(result)
        }

        controller.submitUserText(
            "Odpowiedz jednym krótkim zdaniem po polsku, że lokalny backend działa.",
            object : TextCallTurnController.Listener {
                override fun onApprovedResponse(text: String) {
                    lines += "backend_complete_response=true"
                    lines += "approved_text_nonblank=${text.isNotBlank()}"
                    tts.synthesize(text, object : LocalTtsSpeechOutput.Listener {
                        override fun onPcm16Mono16k(pcm: ByteArray) {
                            lines += "output_pcm_bytes=${pcm.size}"
                            lines += "approved_output_pcm_nonempty=${pcm.isNotEmpty()}"
                            finish(pcm.isNotEmpty())
                        }

                        override fun onError(reason: String) = finish(false, "tts_$reason")
                    })
                }

                override fun onDroppedResponse() = finish(false, "output_dropped")
                override fun onError(reason: String) = finish(false, reason)
            },
        )
    }

    private fun writeReport(context: Context, result: String) {
        try {
            context.openFileOutput(REPORT_FILE, Context.MODE_PRIVATE).bufferedWriter().use { writer ->
                writer.write(result)
                writer.newLine()
            }
        } catch (_: Throwable) {}
    }
}
'''

DEBUG_MANIFEST_TEXT = r'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <!-- Debug-only LAN lab access. Production/release manifests remain cleartext-deny by default. -->
    <application android:usesCleartextTraffic="true" />
</manifest>
'''


def ensure_build_dependency():
    text = BUILD.read_text(encoding="utf-8")
    needle = '    implementation("com.google.code.gson:gson:2.14.0")\n'
    addition = needle + '    implementation("com.squareup.okhttp3:okhttp:5.4.0")\n'
    if 'implementation("com.squareup.okhttp3:okhttp:5.4.0")' not in text:
        if text.count(needle) != 1:
            raise RuntimeError("expected Gson dependency anchor exactly once")
        BUILD.write_text(text.replace(needle, addition, 1), encoding="utf-8")


def write_red():
    ensure_build_dependency()
    TEST.parent.mkdir(parents=True, exist_ok=True)
    TEST.write_text(TEST_TEXT, encoding="utf-8")
    print("local_mac_text_backend_red_written=true")


def write_green():
    BACKEND.parent.mkdir(parents=True, exist_ok=True)
    BACKEND.write_text(BACKEND_TEXT, encoding="utf-8")
    PROBE.write_text(PROBE_TEXT, encoding="utf-8")
    DEBUG_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    DEBUG_MANIFEST.write_text(DEBUG_MANIFEST_TEXT, encoding="utf-8")

    activity = ACTIVITY.read_text(encoding="utf-8")
    anchor = '''    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE, false)) {\n'''
    block = '''    private fun runRequestedProbe() {\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_MAC_TEXT_BACKEND_PROBE, false)) {\n            val baseUrl = intent.getStringExtra(EXTRA_LOCAL_TEXT_BASE_URL).orEmpty()\n            val model = intent.getStringExtra(EXTRA_LOCAL_TEXT_MODEL).orEmpty()\n            if (baseUrl.isBlank() || model.isBlank()) {\n                finishWithError("local_text_backend_config_missing")\n                return\n            }\n            statusView.text = "Running local Mac text backend probe…"\n            Log.i(TAG, "local_mac_text_backend_probe_start=true")\n            LocalMacTextBackendProbe.run(this, baseUrl, model) { result ->\n                runOnUiThread {\n                    statusView.text = result\n                    Log.i(TAG, "local_mac_text_backend_probe_result:\\n$result")\n                    finish()\n                }\n            }\n            return\n        }\n\n        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_SPEECH_PRODUCTION_PROBE, false)) {\n'''
    if activity.count(anchor) != 1:
        raise RuntimeError(f"activity runRequestedProbe anchor expected once, got {activity.count(anchor)}")
    activity = activity.replace(anchor, block, 1)

    const_anchor = '''        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n'''
    const_block = '''        const val LIVE_SHIZUKU_DURATION_MS = 5_000\n        const val EXTRA_RUN_LOCAL_MAC_TEXT_BACKEND_PROBE = "run_local_mac_text_backend_probe"\n        const val EXTRA_LOCAL_TEXT_BASE_URL = "local_text_base_url"\n        const val EXTRA_LOCAL_TEXT_MODEL = "local_text_model"\n        const val EXTRA_RUN_LOCAL_SPEECH_CAPABILITY_PROBE = "run_local_speech_capability_probe"\n'''
    if activity.count(const_anchor) != 1:
        raise RuntimeError(f"activity constant anchor expected once, got {activity.count(const_anchor)}")
    ACTIVITY.write_text(activity.replace(const_anchor, const_block, 1), encoding="utf-8")
    print("local_mac_text_backend_green_written=true")


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "red":
        write_red()
    elif mode == "green":
        write_green()
    else:
        raise SystemExit("usage: local-mac-openai-compatible-backend-v1.py red|green")
