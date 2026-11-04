# Original speech with Japanese furigana and English within the same lyric line.
$ErrorActionPreference = 'Stop'
$taskBuild = Join-Path (Split-Path -Parent $PSScriptRoot) 'build'
New-Item -ItemType Directory -Force -Path $taskBuild | Out-Null
$taskVoice = New-Object -ComObject SAPI.SpVoice
$taskJapanese = $null
$taskEnglish = $null
foreach ($taskToken in $taskVoice.GetVoices()) {
    if ($taskToken.GetDescription() -match 'Japanese') { $taskJapanese = $taskToken }
    if ($taskToken.GetDescription() -match 'English') { $taskEnglish = $taskToken }
}
if (-not $taskJapanese -or -not $taskEnglish) {
    throw 'Install Japanese and English SAPI voices before running this acceptance test.'
}
$taskStream = New-Object -ComObject SAPI.SpFileStream
$taskStream.Format.Type = 22
$taskStream.Open((Join-Path $taskBuild 'smoke-mixed.wav'), 3)
try {
    $taskVoice.AudioOutputStream = $taskStream
    $taskVoice.Rate = -2
    $taskVoice.Voice = $taskJapanese
    [void]$taskVoice.Speak('そらを見上げる。<silence msec="700"/>こんにちは。', 8)
    $taskVoice.Voice = $taskEnglish
    [void]$taskVoice.Speak('Hello world.<silence msec="700"/>', 8)
    $taskVoice.Voice = $taskJapanese
    [void]$taskVoice.Speak('明日も楽しい一日になりますように。', 8)
} finally {
    $taskStream.Close()
}
[IO.File]::WriteAllText((Join-Path $taskBuild 'smoke-mixed.txt'),
    "宇宙(そら)を見上げる。`nこんにちは Hello world.`n明日も楽しい一日になりますように。",
    [Text.UTF8Encoding]::new($false))
