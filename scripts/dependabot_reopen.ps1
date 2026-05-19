$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$repo = 'jinujon007/RE_OS'

# Dependabot closed PRs - comment to reopen
foreach ($pr in @(1, 2, 3)) {
    Write-Host "Requesting reopen on PR #$pr..."
    & $gh pr comment $pr --repo $repo --body "@dependabot reopen"
}

# For pandas and numpy - request recreate (they may need version resolution)
foreach ($pr in @(5, 9)) {
    Write-Host "Requesting recreate on PR #$pr..."
    & $gh pr comment $pr --repo $repo --body "@dependabot recreate"
}

Write-Host "Done. Dependabot will reopen/recreate PRs in ~2-5 min."
