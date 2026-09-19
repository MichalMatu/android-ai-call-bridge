from pathlib import Path

factory = Path('app/src/main/kotlin/pl/michalmatu/aicallbridge/textagent/LocalPhoneLlmBackendFactory.kt')
text = factory.read_text()
old = '''    const val MODEL = "qwen-phone-0.5b"

    private const val SYSTEM_PROMPT =
        "Jesteś lokalnym asystentem prowadzącym rozmowę telefoniczną po polsku. " +
            "Odpowiadaj krótko i naturalnie, najwyżej dwoma zdaniami. " +
            "Nie składaj zamówień, nie akceptuj umów, nie ujawniaj danych wrażliwych i nie podejmuj zobowiązań bez jawnej autoryzacji aplikacji."
'''
new = '''    const val MODEL = "qwen-phone-1.5b"

    internal const val SYSTEM_PROMPT =
        "Jesteś lokalnym asystentem reprezentującym użytkownika w rozmowie telefonicznej po polsku. " +
            "Wejście użytkownika jest automatycznym transkryptem wypowiedzi drugiej strony i może być niepełne lub niedokładne. " +
            "Odpowiadaj krótko i naturalnie, najwyżej jednym zdaniem. Nie wymyślaj faktów, nazw, ofert ani intencji. " +
            "Jeśli transkrypt jest zbyt krótki, niejasny albo wygląda jak fragment powitania lub komunikatu IVR, poproś krótko o kontynuowanie lub doprecyzowanie. " +
            "Nie składaj zamówień, nie akceptuj umów, nie ujawniaj danych wrażliwych i nie podejmuj zobowiązań bez jawnej autoryzacji aplikacji."
'''
if old not in text:
    raise SystemExit('factory pattern not found')
factory.write_text(text.replace(old, new))

probe = Path('app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalPhoneLlmLiveCallProbe.kt')
text = probe.read_text()
old = '    private const val INPUT_CAPTURE_MS = 5_000\n'
new = '    private const val INPUT_CAPTURE_MS = 8_000\n'
if old not in text:
    raise SystemExit('capture pattern not found')
probe.write_text(text.replace(old, new))

test = Path('app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/LocalPhoneLlmBackendFactoryTest.kt')
test.write_text('''package pl.michalmatu.aicallbridge.textagent\n\nimport org.junit.Assert.assertEquals\nimport org.junit.Assert.assertTrue\nimport org.junit.Test\n\nclass LocalPhoneLlmBackendFactoryTest {\n    @Test\n    fun `production phone provider selects qwen 1 point 5b`() {\n        assertEquals("qwen-phone-1.5b", LocalPhoneLlmBackendFactory.MODEL)\n        assertEquals("http://127.0.0.1:18115/v1/", LocalPhoneLlmBackendFactory.BASE_URL)\n    }\n\n    @Test\n    fun `phone prompt treats speech input as imperfect transcript and forbids guessing`() {\n        val prompt = LocalPhoneLlmBackendFactory.SYSTEM_PROMPT.lowercase()\n        assertTrue(prompt.contains("transkrypt"))\n        assertTrue(prompt.contains("nie wymyślaj"))\n        assertTrue(prompt.contains("niejasny"))\n        assertTrue(prompt.contains("ivR".lowercase()))\n    }\n}\n''')

print('qwen15b_quality_patch_applied=true')
