$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$repo = 'jinujon007/RE_OS'
$prs = 6, 7, 8
$done = @()
$maxAttempts = 30
$attempt = 0
$requiredChecks = 'Lint & Syntax Check', 'Docker Compose Validate', 'SQL Schema Syntax', 'Secret Scan (Gitleaks)'

while ($done.Count -lt $prs.Count -and $attempt -lt $maxAttempts) {
    $attempt++
    $time = Get-Date -Format 'HH:mm:ss'
    Write-Host ""
    Write-Host "[Attempt $attempt] $time"

    foreach ($pr in $prs) {
        if ($done -contains $pr) { continue }

        $raw = & $gh pr view $pr --repo $repo --json statusCheckRollup,state 2>&1
        $data = $raw | ConvertFrom-Json -ErrorAction SilentlyContinue

        if (-not $data) {
            Write-Host "  PR #$pr - cannot read"
            continue
        }

        if ($data.state -eq 'MERGED') {
            Write-Host "  PR #$pr - already merged"
            $done += $pr
            continue
        }

        $checks = $data.statusCheckRollup
        if (-not $checks -or $checks.Count -eq 0) {
            Write-Host "  PR #$pr - no checks yet"
            continue
        }

        $passedCount = 0
        $pendingCount = 0
        $failedRequired = $false

        foreach ($check in $checks) {
            $isRequired = $requiredChecks -contains $check.name
            if ($check.conclusion -eq 'SUCCESS' -and $isRequired) {
                $passedCount++
            } elseif (($check.state -eq 'PENDING' -or $check.state -eq 'IN_PROGRESS') -and $isRequired) {
                $pendingCount++
            } elseif ($check.conclusion -eq 'FAILURE' -and $isRequired) {
                $failedRequired = $true
            }
        }

        Write-Host "  PR #$pr - passed=$passedCount/4  pending=$pendingCount  failedRequired=$failedRequired"

        if ($failedRequired) {
            Write-Host "  PR #$pr - required check failed, skipping"
            $done += $pr
            continue
        }

        if ($passedCount -ge 4 -and $pendingCount -eq 0) {
            Write-Host "  PR #$pr - all green, approving and merging..."
            & $gh pr review $pr --approve --repo $repo
            & $gh pr merge $pr --squash --delete-branch --repo $repo
            $done += $pr
        }
    }

    if ($done.Count -lt $prs.Count) {
        Write-Host "  sleeping 60s..."
        Start-Sleep -Seconds 60
    }
}

Write-Host ""
Write-Host "Finished. Done: $($done.Count) of $($prs.Count)"
