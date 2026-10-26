$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$sshArgs = @('-i', './tools/ssh/pro6-linux-ed25519', '-o', 'UserKnownHostsFile=./tools/ssh/known_hosts-ubuntu', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10')
$epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
& ssh.exe @sshArgs root@192.168.76.1 "date -u -s @$epoch; touch /var/lib/systemd/timesync/clock"
if ($LASTEXITCODE -ne 0) { throw 'SSH connection failed' }
& ssh.exe @sshArgs -t -o ExitOnForwardFailure=yes -R 127.0.0.1:1080 root@192.168.76.1
