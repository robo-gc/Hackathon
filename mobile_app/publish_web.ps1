# Publica mobile_app/main.py como PWA estática en ../dist con NeverMind, GPS nativo, Voz (Web Speech) y Sirena (Web Audio)
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
$mobileBridgeScript = @'
  <script>
    (function () {
      var audioCtx = null;
      var sirenTimer = null;
      var sirenOsc = null;
      var sirenGain = null;
      var lastHandledHash = "";

      function ensureAudioContext() {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        if (!audioCtx) {
          audioCtx = new Ctx();
        }
        if (audioCtx.state === "suspended") {
          audioCtx.resume().catch(function () {});
        }
        return audioCtx;
      }

      function unlockMobileAudio() {
        ensureAudioContext();
        if (window.speechSynthesis && window.speechSynthesis.getVoices) {
          window.speechSynthesis.getVoices();
        }
      }
      ["pointerdown", "touchstart", "click"].forEach(function (ev) {
        window.addEventListener(ev, unlockMobileAudio, { passive: true });
      });

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

      function speakSpanish(text) {
        if (!window.speechSynthesis || !text) return;
        try {
          window.speechSynthesis.cancel();
          var u = new SpeechSynthesisUtterance(text);
          u.lang = "es-MX";
          u.rate = 1.0;
          u.pitch = 1.0;
          u.volume = 1.0;
          var voices = window.speechSynthesis.getVoices() || [];
          var esVoice =
            voices.find(function (v) { return v.lang && v.lang.toLowerCase().indexOf("es-mx") === 0; }) ||
            voices.find(function (v) { return v.lang && v.lang.toLowerCase().indexOf("es") === 0; });
          if (esVoice) u.voice = esVoice;
          window.speechSynthesis.speak(u);
        } catch (e) {}
      }

      function stopSpeech() {
        try {
          if (window.speechSynthesis) window.speechSynthesis.cancel();
        } catch (e) {}
      }

      function stopSiren() {
        if (sirenTimer) {
          clearInterval(sirenTimer);
          sirenTimer = null;
        }
        if (sirenOsc) {
          try { sirenOsc.stop(); sirenOsc.disconnect(); } catch (e) {}
          sirenOsc = null;
        }
        if (sirenGain) {
          try { sirenGain.disconnect(); } catch (e) {}
          sirenGain = null;
        }
      }

      function startSiren() {
        stopSiren();
        var ctx = ensureAudioContext();
        if (!ctx) return;
        try {
          var freqs = [1200, 820, 1320, 820];
          var idx = 0;
          sirenOsc = ctx.createOscillator();
          sirenGain = ctx.createGain();
          sirenOsc.type = "triangle";
          sirenOsc.frequency.setValueAtTime(freqs[0], ctx.currentTime);
          sirenGain.gain.setValueAtTime(0.45, ctx.currentTime);
          sirenOsc.connect(sirenGain);
          sirenGain.connect(ctx.destination);
          sirenOsc.start();
          sirenTimer = setInterval(function () {
            if (!sirenOsc || !audioCtx) return;
            idx = (idx + 1) % freqs.length;
            sirenOsc.frequency.setValueAtTime(freqs[idx], audioCtx.currentTime);
          }, 240);
        } catch (e) {}
      }

      function handleHash() {
        var h = window.location.hash || "";
        if (!h || h === lastHandledHash) return;
        if (h.indexOf("#/request-gps") === 0) {
          lastHandledHash = h;
          requestBrowserGps();
        } else if (h.indexOf("#/speak/") === 0) {
          lastHandledHash = h;
          var parts = h.split("/");
          var encoded = parts.slice(3).join("/");
          if (encoded) {
            try { speakSpanish(decodeURIComponent(encoded)); } catch (e) {}
          }
        } else if (h.indexOf("#/speak-stop") === 0) {
          lastHandledHash = h;
          stopSpeech();
        } else if (h.indexOf("#/siren-start") === 0) {
          lastHandledHash = h;
          startSiren();
        } else if (h.indexOf("#/siren-stop") === 0) {
          lastHandledHash = h;
          stopSiren();
        }
      }

      window.addEventListener("hashchange", handleHash);
      window.addEventListener("load", handleHash);
    })();
  </script>
</head>
'@
if ($html -notmatch "requestBrowserGps") {
  $html = $html -replace "</head>", $mobileBridgeScript
  Set-Content -Path $indexPath -Value $html -Encoding UTF8
}

Write-Host "Listo! dist/ generado desde Hackathon/mobile_app (GPS + Voz + Sirena) en: $distDir" -ForegroundColor Green
