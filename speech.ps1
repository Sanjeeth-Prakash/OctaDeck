param([ValidateSet('transcribe','speak')][string]$Mode)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$payload = [Console]::In.ReadToEnd()
if ($Mode -eq 'speak') {
    $voice = [System.Speech.Synthesis.SpeechSynthesizer]::new()
    $stream = [System.IO.MemoryStream]::new()
    try {
        $voice.SetOutputToWaveStream($stream)
        $voice.Speak([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)))
        [Console]::Write([Convert]::ToBase64String($stream.ToArray()))
    } finally {
        $voice.Dispose()
        $stream.Dispose()
    }
} else {
    $installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
    if ($installed.Count -eq 0) { throw 'Windows has no installed speech recognizer.' }
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($installed[0].Id)
    $stream = [System.IO.MemoryStream]::new([Convert]::FromBase64String($payload))
    try {
        $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
        $engine.SetInputToWaveStream($stream)
        $result = $engine.Recognize()
        $text = if ($null -eq $result) { '' } else { $result.Text }
        [Console]::Write([Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($text)))
    } finally {
        $engine.Dispose()
        $stream.Dispose()
    }
}
