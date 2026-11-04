# Generate original speech locally; no copyrighted song or external audio is used.
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
$taskBuild = Join-Path $taskProject 'build'
New-Item -ItemType Directory -Force -Path $taskBuild | Out-Null
$taskVoice = New-Object -ComObject SAPI.SpVoice
$taskVoices = $taskVoice.GetVoices()
for ($taskIndex = 0; $taskIndex -lt $taskVoices.Count; $taskIndex++) {
    if ($taskVoices.Item($taskIndex).GetDescription() -match 'English') {
        $taskVoice.Voice = $taskVoices.Item($taskIndex)
        break
    }
}
$taskStream = New-Object -ComObject SAPI.SpFileStream
$taskStream.Format.Type = 22
$taskStream.Open((Join-Path $taskBuild 'smoke-en.wav'), 3)
try {
    $taskVoice.AudioOutputStream = $taskStream
    $taskVoice.Rate = -2
    [void]$taskVoice.Speak('Hello world. <silence msec="600"/> This is a test.', 8)
} finally {
    $taskStream.Close()
}
[IO.File]::WriteAllText((Join-Path $taskBuild 'smoke-en.txt'), "Hello world.`nThis is a test.`n", [Text.UTF8Encoding]::new($false))
