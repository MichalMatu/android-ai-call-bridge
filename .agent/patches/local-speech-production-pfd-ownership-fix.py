from pathlib import Path

path = Path("app/src/main/kotlin/pl/michalmatu/aicallbridge/localspeech/OnDeviceSpeechInput.kt")
text = path.read_text(encoding="utf-8")
text = text.replace("import java.io.FileOutputStream\n", "import java.io.OutputStream\n")
text = text.replace("private var writer: FileOutputStream? = null", "private var writer: OutputStream? = null")
text = text.replace("val currentWriter: FileOutputStream?", "val currentWriter: OutputStream?")
text = text.replace("val writeStream = FileOutputStream(pipe[1].fileDescriptor)", "val writeStream = ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])")
text = text.replace("                try { pipe[1].close() } catch (_: Throwable) {}\n", "")
path.write_text(text, encoding="utf-8")
print("local_speech_production_pfd_ownership_fix_applied=true")
