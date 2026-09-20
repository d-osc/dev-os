param(
    [ValidateRange(128, 32768)][int]$MemoryMiB = 512,
    [ValidateSet('tcg', 'whpx')][string]$Acceleration = 'tcg'
)
$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$imagePath = Join-Path $projectPath 'out/images'
$kernelPath = Join-Path $imagePath 'bzImage'
$diskPath = Join-Path $imagePath 'rootfs.ext4'
$promptDiskPath = Join-Path $imagePath 'rootfs-prompt.ext4'
if ((Test-Path -LiteralPath $promptDiskPath) -and
    (!(Test-Path -LiteralPath $diskPath) -or
     (Get-Item -LiteralPath $promptDiskPath).LastWriteTimeUtc -gt (Get-Item -LiteralPath $diskPath).LastWriteTimeUtc)) {
    $diskPath = $promptDiskPath
}
if (!(Test-Path -LiteralPath $kernelPath) -or !(Test-Path -LiteralPath $diskPath)) {
    throw 'Build and export Dev OS images to out/images first.'
}
$qemuPath = (Get-Command qemu-system-x86_64.exe -ErrorAction Stop).Source
& $qemuPath -accel $Acceleration -machine pc -m $MemoryMiB -smp 2 -nographic -snapshot `
    -kernel $kernelPath -drive "file=$diskPath,format=raw,if=virtio" `
    -append 'root=/dev/vda rw console=ttyS0' `
    -netdev user,id=net0 -device virtio-net-pci,netdev=net0
exit $LASTEXITCODE
