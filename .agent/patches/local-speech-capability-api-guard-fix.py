from pathlib import Path

path = Path("app/src/main/kotlin/pl/michalmatu/aicallbridge/LocalSpeechCapabilityProbe.kt")
text = path.read_text(encoding="utf-8")
old = '''        val onDeviceAvailable = Build.VERSION.SDK_INT >= 31 &&
            SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)
        lines += "on_device_recognition_available=$onDeviceAvailable"
        lines += "audio_source_pfd_api_available=${Build.VERSION.SDK_INT >= 33}"
        lines += "target_pcm_format=mono,pcm16,16000"

        if (!onDeviceAvailable) {
            lines += "stt_support_probe=unavailable"
            runTtsProbe(appContext, lines, callback)
            return
        }

        val recognizer = try {
            SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        } catch (error: Throwable) {
'''
new = '''        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            lines += "on_device_recognition_available=false"
            lines += "audio_source_pfd_api_available=false"
            lines += "target_pcm_format=mono,pcm16,16000"
            lines += "stt_support_probe=api_below_31"
            runTtsProbe(appContext, lines, callback)
            return
        }

        val onDeviceAvailable = SpeechRecognizer.isOnDeviceRecognitionAvailable(appContext)
        lines += "on_device_recognition_available=$onDeviceAvailable"
        lines += "audio_source_pfd_api_available=${Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU}"
        lines += "target_pcm_format=mono,pcm16,16000"

        if (!onDeviceAvailable) {
            lines += "stt_support_probe=unavailable"
            runTtsProbe(appContext, lines, callback)
            return
        }

        val recognizer = try {
            SpeechRecognizer.createOnDeviceSpeechRecognizer(appContext)
        } catch (error: Throwable) {
'''
if text.count(old) != 1:
    raise RuntimeError(f"expected one SDK guard block, got {text.count(old)}")
text = text.replace(old, new, 1)
text = text.replace("if (Build.VERSION.SDK_INT < 33) {", "if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {", 1)
path.write_text(text, encoding="utf-8")
print("local_speech_api_guard_fix_applied=true")
