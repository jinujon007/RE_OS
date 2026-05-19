$gh = 'C:\Program Files\GitHub CLI\gh.exe'
& $gh api repos/jinujon007/RE_OS/branches/master/protection --jq '.required_status_checks.contexts'
