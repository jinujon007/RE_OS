$gh = 'C:\Program Files\GitHub CLI\gh.exe'

$tmp = [System.IO.Path]::GetTempFileName() + ".json"

# PATCH only the required_status_checks endpoint — avoids restrictions issue entirely
$content = '{"strict":true,"contexts":["Lint & Syntax Check","Docker Compose Validate","SQL Schema Syntax","Secret Scan (Gitleaks)","Conventional Commit Title"]}'

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($tmp, $content, $utf8NoBom)

Write-Host "Patching required status checks..."
& $gh api repos/jinujon007/RE_OS/branches/master/protection/required_status_checks --method PATCH --input $tmp 2>&1 | Select-Object -First 5
Remove-Item $tmp -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Verifying:"
& $gh api repos/jinujon007/RE_OS/branches/master/protection --jq '.required_status_checks.contexts'
