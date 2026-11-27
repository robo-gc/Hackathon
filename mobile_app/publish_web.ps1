# Publica mobile_app/main.py como PWA estática en ../dist con NeverMind y puente GPS nativo del navegador
$ErrorActionPreference = "Stop"
$mobileDir = $PSScriptRoot
$repoRoot = Split-Path -Parent $mobileDir
$distDir = Join-Path $repoRoot "dist"
$fletExe = "C:\Users\emijc\.gemini\antigravity\scratch\map-inclusive\.venv\Scripts\flet.exe"
if (-not (Test-Path $fletExe)) { $fletExe = "flet" }

Set-Location $mobileDir
& $fletExe publish "main.py" `
  -a "assets" `
  --distpath $distDir `
  --app-name "Map Inclusive" `
  --app-short-name "MapInclusive" `
  --app-description "Rutas accesibles con Gemini - Equipo Apex soa, Campus Coyoacan" `
  --pwa-background-color "#FFFFFF" `
  --pwa-theme-color "#1B2354" `
  --route-url-strategy hash

Set-Content -Path (Join-Path $distDir "_headers") -Value "/fonts/*`n  Access-Control-Allow-Origin: *`n  Cache-Control: public, max-age=31536000, immutable"

$indexPath = Join-Path $distDir "index.html"
$html = Get-Content -Path $indexPath -Raw -Encoding UTF8
$gpsScript = @'
  <script>
    (function () {
      function requestBrowserGps() {
        if (!navigator.geolocation) {
          window.location.hash = "#/gps-error/unsupported";
          return;
        }
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            var lat = pos.coords.latitude.toFixed(6);
            var lon = pos.coords.longitude.toFixed(6);
            var acc = Math.round(pos.coords.accuracy || 0);
            window.location.hash = "#/gps/" + lat + "/" + lon + "/" + acc;
          },
          function (err) {
            window.location.hash = "#/gps-error/" + (err && err.code ? err.code : "denied");
          },
          { enableHighAccuracy: true, timeout: 10000, maximumAge: 15000 }
        );
      }
      function checkHash() {
        if (window.location.hash && window.location.hash.indexOf("#/request-gps") === 0) {
          requestBrowserGps();
        }
      }
      window.addEventListener("hashchange", checkHash);
      window.addEventListener("load", checkHash);
    })();
  </script>
</head>
'@
if ($html -notmatch "requestBrowserGps") {
  $html = $html -replace "</head>", $gpsScript
  Set-Content -Path $indexPath -Value $html -Encoding UTF8
}

Write-Host "Listo! dist/ generado desde Hackathon/mobile_app en: $distDir" -ForegroundColor Green
