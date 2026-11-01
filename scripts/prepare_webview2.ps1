$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force vendor | Out-Null
$path = Join-Path $PWD 'vendor/MicrosoftEdgeWebview2Setup.exe'
Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $path
$signature = Get-AuthenticodeSignature -LiteralPath $path
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    Remove-Item -LiteralPath $path
    throw 'Microsoft WebView2 bootstrapper signature validation failed'
}
Get-FileHash -Algorithm SHA256 -LiteralPath $path | Format-List
