$gh = 'C:\Program Files\GitHub CLI\gh.exe'
& $gh pr list --repo jinujon007/RE_OS --state open --json number,title,statusCheckRollup 2>&1
