# Linux Island for Windows: install for the current user (no administrator needed), or remove it again.
#   install.cmd                 install (or update) and start it
#   install.cmd -Uninstall      remove it (your settings in %APPDATA%\linux-island stay)
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"

$Name      = "Linux Island"
$Source    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target    = Join-Path $env:LOCALAPPDATA "Programs\Linux Island"
$StartMenu = Join-Path ([Environment]::GetFolderPath("Programs")) "Linux Island"
$RunKey    = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
$AppsKey   = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\LinuxIsland"

function Stop-Island {
    # only this installation's Python, nothing else that happens to run Python
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

if ($Uninstall) {
    Stop-Island
    Remove-ItemProperty -Path $RunKey -Name $Name -ErrorAction SilentlyContinue
    Remove-Item -Path $AppsKey -Recurse -ErrorAction SilentlyContinue
    Remove-Item -Path $StartMenu -Recurse -Force -ErrorAction SilentlyContinue
    if ($Source.StartsWith($Target, [StringComparison]::OrdinalIgnoreCase)) {
        Set-Location $env:TEMP   # can't remove the folder we're running from while inside it
    }
    Remove-Item -Path $Target -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "$Name is removed. Your settings stay in $env:APPDATA\linux-island (delete that folder to remove them too)."
    exit 0
}

if (-not (Test-Path (Join-Path $Source "python\pythonw.exe"))) {
    throw "Run this from the unpacked Linux Island folder (python\pythonw.exe not found next to it)."
}
Write-Host "Installing $Name into $Target ..."
Stop-Island
if (-not $Source.Equals($Target, [StringComparison]::OrdinalIgnoreCase)) {
    if (Test-Path $Target) { Remove-Item -Path $Target -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -Path (Join-Path $Source "*") -Destination $Target -Recurse -Force
}
Get-ChildItem -Path $Target -Recurse -File | Unblock-File   # downloaded files: no "from the internet" prompts

$pythonw = Join-Path $Target "python\pythonw.exe"
$icon    = Join-Path $Target "linux-island.ico"
$version = (Get-Content (Join-Path $Target "VERSION") -ErrorAction SilentlyContinue) -join ""

# Start menu
$shell = New-Object -ComObject WScript.Shell
New-Item -ItemType Directory -Force -Path $StartMenu | Out-Null
function New-Shortcut($file, $target, $arguments, $description) {
    $s = $shell.CreateShortcut((Join-Path $StartMenu $file))
    $s.TargetPath = $target
    $s.Arguments = $arguments
    $s.WorkingDirectory = $Target
    $s.IconLocation = $icon
    $s.Description = $description
    $s.Save()
}
New-Shortcut "Linux Island.lnk" $pythonw "-m linux_island" "Dynamic island for the desktop"
New-Shortcut "Linux Island Settings.lnk" $pythonw "-m linux_island --settings" "Settings for Linux Island"
New-Shortcut "Uninstall Linux Island.lnk" "powershell.exe" `
    "-NoProfile -ExecutionPolicy Bypass -File `"$Target\install.ps1`" -Uninstall" "Remove Linux Island"

# start at sign-in (Settings > General > Start on login turns it off again)
Set-ItemProperty -Path $RunKey -Name $Name -Value "`"$pythonw`" -m linux_island"

# Settings > Apps lists it, with Uninstall
New-Item -Path $AppsKey -Force | Out-Null
Set-ItemProperty -Path $AppsKey -Name DisplayName -Value $Name
Set-ItemProperty -Path $AppsKey -Name DisplayVersion -Value $version
Set-ItemProperty -Path $AppsKey -Name Publisher -Value "Linux Island"
Set-ItemProperty -Path $AppsKey -Name DisplayIcon -Value $icon
Set-ItemProperty -Path $AppsKey -Name InstallLocation -Value $Target
Set-ItemProperty -Path $AppsKey -Name UninstallString -Value "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Target\install.ps1`" -Uninstall"
Set-ItemProperty -Path $AppsKey -Name NoModify -Value 1 -Type DWord
Set-ItemProperty -Path $AppsKey -Name NoRepair -Value 1 -Type DWord

Start-Process -FilePath $pythonw -ArgumentList "-m", "linux_island" -WorkingDirectory $Target
Write-Host "Done. The pill is at the top of the screen; on the first start the settings open with a short welcome."
Write-Host "It starts by itself when you sign in. Start menu: Linux Island, Linux Island Settings, Uninstall Linux Island."
