from pathlib import Path

root = Path.cwd()
runtime = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeMode.kt"
backend = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/LocalOpenAiCompatibleTextBackend.kt"
factory = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/LocalPhoneLlmBackendFactory.kt"
probe = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalPhoneLlmSpeechPipelineProbe.kt"
activity = root / "app/src/main/kotlin/pl/michalmatu/aicallbridge/DiagnosticProbeActivity.kt"

s = runtime.read_text()
old = '''enum class TextLlmProvider(val displayName: String) {\n    OPENAI_TEXT("OpenAI API (text)"),\n    LOCAL_MAC_LLM("Local LLM server (Mac)"),\n'''
new = '''enum class TextLlmProvider(val displayName: String) {\n    OPENAI_TEXT("OpenAI API (text)"),\n    LOCAL_PHONE_LLM("Local LLM (S22)"),\n    LOCAL_MAC_LLM("Local LLM server (Mac)"),\n'''
if new not in s:
    if s.count(old) != 1:
        raise RuntimeError("runtime enum anchor mismatch")
    s = s.replace(old, new, 1)
runtime.write_text(s)

s = backend.read_text()
old = '''internal class LocalOpenAiTextBackendConfig(\n    baseUrl: String,\n    model: String,\n    bearerToken: String? = null,\n) {\n    val model: String = model.trim()\n    val bearerToken: String? = bearerToken?.trim()?.takeIf { it.isNotEmpty() }\n'''
new = '''internal class LocalOpenAiTextBackendConfig(\n    baseUrl: String,\n    model: String,\n    bearerToken: String? = null,\n    systemPrompt: String? = null,\n) {\n    val model: String = model.trim()\n    val bearerToken: String? = bearerToken?.trim()?.takeIf { it.isNotEmpty() }\n    val systemPrompt: String? = systemPrompt?.trim()?.takeIf { it.isNotEmpty() }\n'''
if new not in s:
    if s.count(old) != 1:
        raise RuntimeError("backend config constructor anchor mismatch")
    s = s.replace(old, new, 1)
anchor = '''        if (this.bearerToken != null) {\n            require(this.bearerToken.length <= MAX_TOKEN_CHARS) { "local text bearer token is too long" }\n            require(!STANDARD_OPENAI_KEY.matches(this.bearerToken)) {\n                "standard OpenAI API keys must never be stored in the local Mac backend config"\n            }\n        }\n\n'''
insert = anchor + '''        if (this.systemPrompt != null) {\n            require(this.systemPrompt.length <= MAX_SYSTEM_PROMPT_CHARS) {\n                "local text system prompt is too long"\n            }\n        }\n\n'''
if 'MAX_SYSTEM_PROMPT_CHARS' not in s:
    if s.count(anchor) != 1:
        raise RuntimeError("backend validation anchor mismatch")
    s = s.replace(anchor, insert, 1)
old_const = '''        const val MAX_MODEL_CHARS = 160\n        const val MAX_TOKEN_CHARS = 512\n'''
new_const = '''        const val MAX_MODEL_CHARS = 160\n        const val MAX_TOKEN_CHARS = 512\n        const val MAX_SYSTEM_PROMPT_CHARS = 4_000\n'''
if new_const not in s:
    if s.count(old_const) != 1:
        raise RuntimeError("backend constants anchor mismatch")
    s = s.replace(old_const, new_const, 1)
old_messages = '''            add("messages", com.google.gson.JsonArray().apply {\n                add(JsonObject().apply {\n                    addProperty("role", "user")\n                    addProperty("content", userText)\n                })\n            })\n'''
new_messages = '''            add("messages", com.google.gson.JsonArray().apply {\n                config.systemPrompt?.let { prompt ->\n                    add(JsonObject().apply {\n                        addProperty("role", "system")\n                        addProperty("content", prompt)\n                    })\n                }\n                add(JsonObject().apply {\n                    addProperty("role", "user")\n                    addProperty("content", userText)\n                })\n            })\n'''
if new_messages not in s:
    if s.count(old_messages) != 1:
        raise RuntimeError("backend messages anchor mismatch")
    s = s.replace(old_messages, new_messages, 1)
backend.write_text(s)

factory.write_text('''package pl.michalmatu.aicallbridge.textagent\n\n/** Production configuration for the proven llama.cpp/Qwen endpoint on the S22 itself. */\ninternal object LocalPhoneLlmBackendFactory {\n    const val BASE_URL = "http://127.0.0.1:18115/v1/"\n    const val MODEL = "qwen-phone-0.5b"\n\n    private const val SYSTEM_PROMPT =\n        "Jesteś lokalnym asystentem prowadzącym rozmowę telefoniczną po polsku. " +\n            "Odpowiadaj krótko i naturalnie, najwyżej dwoma zdaniami. " +\n            "Nie składaj zamówień, nie akceptuj umów, nie ujawniaj danych wrażliwych i nie podejmuj zobowiązań bez jawnej autoryzacji aplikacji."\n\n    fun create(): TextCallAgentBackend = LocalOpenAiCompatibleTextBackend(\n        LocalOpenAiTextBackendConfig(\n            baseUrl = BASE_URL,\n            model = MODEL,\n            systemPrompt = SYSTEM_PROMPT,\n        ),\n    )\n}\n''')

s = probe.read_text()
s = s.replace('import pl.michalmatu.aicallbridge.textagent.LocalOpenAiCompatibleTextBackend\n', '')
s = s.replace('import pl.michalmatu.aicallbridge.textagent.LocalOpenAiTextBackendConfig\n', '')
if 'import pl.michalmatu.aicallbridge.textagent.LocalPhoneLlmBackendFactory\n' not in s:
    anchor_import = 'import pl.michalmatu.aicallbridge.textagent.CallTextAgentOutputApprovalPolicy\n'
    if s.count(anchor_import) != 1:
        raise RuntimeError("probe import anchor mismatch")
    s = s.replace(anchor_import, anchor_import + 'import pl.michalmatu.aicallbridge.textagent.LocalPhoneLlmBackendFactory\n', 1)
old_sig = '    fun run(context: Context, baseUrl: String, model: String, callback: (String) -> Unit) {\n'
new_sig = '    fun run(context: Context, callback: (String) -> Unit) {\n'
if new_sig not in s:
    if s.count(old_sig) != 1:
        raise RuntimeError("probe signature anchor mismatch")
    s = s.replace(old_sig, new_sig, 1)
old_backend = '            LocalOpenAiCompatibleTextBackend(LocalOpenAiTextBackendConfig(baseUrl, model))\n'
new_backend = '            LocalPhoneLlmBackendFactory.create()\n'
if new_backend not in s:
    if s.count(old_backend) != 1:
        raise RuntimeError("probe backend anchor mismatch")
    s = s.replace(old_backend, new_backend, 1)
probe.write_text(s)

s = activity.read_text()
old_block = '''        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_PHONE_LLM_SPEECH_PIPELINE_PROBE, false)) {\n            val baseUrl = intent.getStringExtra(EXTRA_LOCAL_TEXT_BASE_URL).orEmpty()\n            val model = intent.getStringExtra(EXTRA_LOCAL_TEXT_MODEL).orEmpty()\n            if (baseUrl.isBlank() || model.isBlank()) {\n                finishWithError("local_phone_llm_pipeline_config_missing")\n                return\n            }\n            statusView.text = "Running local phone LLM speech pipeline probe…"\n            Log.i(TAG, "local_phone_llm_speech_pipeline_probe_start=true")\n            LocalPhoneLlmSpeechPipelineProbe.run(this, baseUrl, model) { result ->\n'''
new_block = '''        if (intent.getBooleanExtra(EXTRA_RUN_LOCAL_PHONE_LLM_SPEECH_PIPELINE_PROBE, false)) {\n            statusView.text = "Running local phone LLM speech pipeline probe…"\n            Log.i(TAG, "local_phone_llm_speech_pipeline_probe_start=true")\n            LocalPhoneLlmSpeechPipelineProbe.run(this) { result ->\n'''
if new_block not in s:
    if s.count(old_block) != 1:
        raise RuntimeError("activity phone probe anchor mismatch")
    s = s.replace(old_block, new_block, 1)
activity.write_text(s)
print("local_phone_provider_green_patch_applied=true")
