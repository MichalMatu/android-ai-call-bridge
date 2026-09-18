from pathlib import Path

TEST = Path.cwd() / "app/src/test/kotlin/pl/michalmatu/aicallbridge/textagent/LocalOpenAiCompatibleTextBackendTest.kt"

text = TEST.read_text(encoding="utf-8")
needle = r"\\r\\n"
count = text.count(needle)
if count < 5:
    raise RuntimeError(f"expected escaped CRLF fixture markers, got {count}")
TEST.write_text(text.replace(needle, r"\r\n"), encoding="utf-8")
print(f"local_mac_backend_fixture_crlf_fixed={count}")
