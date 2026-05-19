$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$repo = 'jinujon007/RE_OS'
$maxAttempts = 40
$attempt = 0
$totalMerged = 0
$requiredChecks = 'Lint & Syntax Check', 'Docker Compose Validate', 'SQL Schema Syntax', 'Secret Scan (Gitleaks)'

Write-Host "Waiting for Dependabot to reopen PRs and CI to pass. Polling every 60s..."
Write-Host "Required checks: $($requiredChecks -join ', ')"
Write-Host "(Note: Conventional Commit Title now required too - Dependabot titles are valid)"
Write-Host ""

while ($attempt -lt $maxAttempts) {
    $attempt++
    $time = Get-Date -Format 'HH:mm:ss'
    Write-Host "[Attempt $attempt] $time"

    $rawPRs = & $gh pr list --repo $repo --state open --json number,title,statusCheckRollup,state 2>&1
    $prs = $rawPRs | ConvertFrom-Json -ErrorAction SilentlyContinue

    if (-not $prs -or $prs.Count -eq 0) {
        Write-Host "  No open PRs yet. Waiting..."
        Start-Sleep -Seconds 60
        continue
    }

    $allDone = $true

    foreach ($pr in $prs) {
        $num = $pr.number
        $title = $pr.title.Substring(0, [Math]::Min(60, $pr.title.Length))
        $checks = $pr.statusCheckRollup

        if (-not $checks -or $checks.Count -eq 0) {
            Write-Host "  PR #$num [$title] - checks not started"
            $allDone = $false
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

        Write-Host "  PR #$num [$title] - passed=$passedCount/4 pending=$pendingCount failed=$failedRequired"

        if ($failedRequired) {
            Write-Host "  PR #$num - REQUIRED CHECK FAILED. Review manually."
            continue
        }

        if ($passedCount -ge 4 -and $pendingCount -eq 0) {
            Write-Host "  PR #$num - all green. Approving and merging..."
            & $gh pr review $num --approve --repo $repo 2>&1 | Out-Null
            $result = & $gh pr merge $num --squash --delete-branch --repo $repo 2>&1
            Write-Host "  Result: $result"
            $totalMerged++
        } else {
            $allDone = $false
        }
    }

    $remaining = & $gh pr list --repo $repo --state open --json number 2>&1 | ConvertFrom-Json
    if ($remaining.Count -eq 0 -and $attempt -gt 1) {
        Write-Host ""
        Write-Host "All PRs merged. Total merged this session: $totalMerged"
        break
    }

    if (-not $allDone) {
        Write-Host "  Sleeping 60s..."
        Start-Sleep -Seconds 60
    }
}

Write-Host ""
Write-Host "Final open PR count:"
& $gh pr list --repo $repo --state open --json number,title | ConvertFrom-Json | ForEach-Object { Write-Host "  #$($_.number) $($_.title)" }
Write-Host "Done."
