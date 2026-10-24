$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Chưa có .venv312. Hãy tạo môi trường và cài requirements.txt trước."
}
& $Python -m PyInstaller --noconfirm --clean --windowed --name GPS_Journey_Analyzer `
    --collect-all matplotlib --collect-all openpyxl `
    (Join-Path $PSScriptRoot "main.py")
Write-Host "Đã tạo: dist\GPS_Journey_Analyzer\GPS_Journey_Analyzer.exe"

