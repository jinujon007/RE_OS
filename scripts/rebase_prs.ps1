$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$repo = 'jinujon007/RE_OS'
$prs = @(6, 7, 8)

foreach ($pr in $prs) {
    Write-Host "Triggering rebase on PR #$pr..."
    & $gh pr comment $pr --repo $repo --body "@dependabot rebase"
    Write-Host "Done PR #$pr"
}
Write-Host "Rebase requests sent. Wait ~5 min for CI to run, then re-run approve_and_merge.ps1"
