from pathlib import Path

root = Path.cwd()
runtime_test = root / "app/src/test/kotlin/pl/michalmatu/aicallbridge/runtime/CallRuntimeModeTest.kt"
backend_test = root / "app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/LocalOpenAiCompatibleTextBackendTest.kt"

s = runtime_test.read_text()
anchor = '        assertEquals(TextLlmProvider.LOCAL_MAC_LLM, TextLlmProvider.fromStored("LOCAL_MAC_LLM"))\n'
line = '        assertEquals(TextLlmProvider.LOCAL_PHONE_LLM, TextLlmProvider.fromStored("LOCAL_PHONE_LLM"))\n'
if line not in s:
    if s.count(anchor) != 1:
        raise RuntimeError("runtime test anchor mismatch")
    s = s.replace(anchor, anchor + line, 1)
runtime_test.write_text(s)

s = backend_test.read_text()
old = '''                LocalOpenAiTextBackendConfig(\n                    baseUrl = server.baseUrl(),\n                    model = "fixture-model",\n                ),'''
new = '''                LocalOpenAiTextBackendConfig(\n                    baseUrl = server.baseUrl(),\n                    model = "fixture-model",\n                    systemPrompt = "Krótki systemowy test telefonu.",\n                ),'''
if new not in s:
    if s.count(old) != 1:
        raise RuntimeError("backend config test anchor mismatch")
    s = s.replace(old, new, 1)
anchor2 = '            assertTrue(request.contains("\\\"role\\\":\\\"user\\\""))\n'
insert2 = '            assertTrue(request.contains("\\\"role\\\":\\\"system\\\""))\n            assertTrue(request.contains("Krótki systemowy test telefonu."))\n'
if insert2 not in s:
    if s.count(anchor2) != 1:
        raise RuntimeError("backend request test anchor mismatch")
    s = s.replace(anchor2, insert2 + anchor2, 1)
backend_test.write_text(s)
print("local_phone_provider_red_patch_applied=true")
