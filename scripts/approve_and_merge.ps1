$gh = 'C:\Program Files\GitHub CLI\gh.exe'
$repo = 'jinujon007/RE_OS'
$prs = @(4, 6, 7, 8)

foreach ($pr in $prs) {
    Write-Host "Approving PR #$pr..."
    & $gh pr review $pr --approve --repo $repo
    Write-Host "Merging PR #$pr..."
    & $gh pr merge $pr --squash --delete-branch --repo $repo
    Write-Host "Done PR #$pr"
    Write-Host "---"
}
Write-Host "All PRs processed."
