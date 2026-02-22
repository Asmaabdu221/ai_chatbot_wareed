$ErrorActionPreference = "Stop"

# Usage:
#   $env:API_BASE="http://127.0.0.1:8000"
#   $env:AUTH_TOKEN="<jwt>"
#   $env:CONV_ID="<conversation-uuid>"
#   ./scripts/manual_backend_checks.ps1

$base = $env:API_BASE
if (-not $base) { $base = "http://127.0.0.1:8000" }

Write-Host "1) Hours question (KB direct / router fixed)"
curl.exe -s -X POST "$base/api/chat" -H "Content-Type: application/json" `
  -d "{\"message\":\"متى ساعات الدوام عندكم؟\",\"include_knowledge\":true}"
Write-Host "`n"

Write-Host "2) Price question"
curl.exe -s -X POST "$base/api/chat" -H "Content-Type: application/json" `
  -d "{\"message\":\"كم سعر تحليل فيتامين د؟\",\"include_knowledge\":true}"
Write-Host "`n"

Write-Host "3) Availability"
curl.exe -s -X POST "$base/api/chat" -H "Content-Type: application/json" `
  -d "{\"message\":\"هل تحليل HbA1c متوفر؟\",\"include_knowledge\":true}"
Write-Host "`n"

Write-Host "4) Symptoms guidance"
curl.exe -s -X POST "$base/api/chat" -H "Content-Type: application/json" `
  -d "{\"message\":\"عندي تساقط شعر، وش تنصحوني؟\",\"include_knowledge\":true}"
Write-Host "`n"

if ($env:AUTH_TOKEN -and $env:CONV_ID) {
  Write-Host "5) PDF attachment summary (conversation endpoint)"
  curl.exe -s -X POST "$base/api/conversations/$($env:CONV_ID)/messages" `
    -H "Authorization: Bearer $($env:AUTH_TOKEN)" `
    -F "message=اشرح التحاليل ووش معناها" `
    -F "attachment=@sample-report.pdf;type=application/pdf" `
    -F "attachment_type=pdf"
  Write-Host "`n"
} else {
  Write-Host "5) Skipped PDF multipart check (set AUTH_TOKEN + CONV_ID + sample-report.pdf)."
}
