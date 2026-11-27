# Publica mobile_app/main.py como PWA estática en ../dist con BroadcastChannel (iOS/Android GPS + Voz + Sirena HTML5 WAV)
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
      var channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("map_inclusive_native") : null;
      var audioCtx = null;
      var sirenAudio = null;
      var sirenWavUrl = null;
      var silentWavUrl = null;
      var sirenActive = false;
      var sirenTimer = null;
      var sirenOsc = null;
      var sirenGain = null;
      var audioUnlocked = false;

      // Genera un WAV 100% silencioso (ceros) SOLO para desbloquear <audio> en iOS sin emitir ningún ruido
      function buildSilentWavUrl() {
        var sampleRate = 8000;
        var totalSamples = 400; // 0.05 s de silencio absoluto
        var buffer = new ArrayBuffer(44 + totalSamples * 2);
        var view = new DataView(buffer);
        function writeStr(offset, s) {
          for (var i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
        }
        writeStr(0, "RIFF");
        view.setUint32(4, 36 + totalSamples * 2, true);
        writeStr(8, "WAVE");
        writeStr(12, "fmt ");
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeStr(36, "data");
        view.setUint32(40, totalSamples * 2, true);
        return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
      }

      // Genera un WAV real en memoria (PCM 16-bit) para reproducirlo con <audio> nativo en iOS Safari y Android Chrome
      function buildSirenWavUrl() {
        if (sirenWavUrl) return sirenWavUrl;
        var sampleRate = 16000;
        var tones = [
          [1200, 0.24],
          [820, 0.24],
          [1320, 0.24],
          [820, 0.24]
        ];
        var totalSamples = 0;
        for (var t = 0; t < tones.length; t++) {
          totalSamples += Math.floor(sampleRate * tones[t][1]);
        }
        var buffer = new ArrayBuffer(44 + totalSamples * 2);
        var view = new DataView(buffer);
        function writeStr(offset, s) {
          for (var i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
        }
        writeStr(0, "RIFF");
        view.setUint32(4, 36 + totalSamples * 2, true);
        writeStr(8, "WAVE");
        writeStr(12, "fmt ");
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        writeStr(36, "data");
        view.setUint32(40, totalSamples * 2, true);

        var offset = 44;
        for (var k = 0; k < tones.length; k++) {
          var freq = tones[k][0];
          var count = Math.floor(sampleRate * tones[k][1]);
          for (var i = 0; i < count; i++) {
            var sample = Math.round(28000 * Math.sin((2 * Math.PI * freq * i) / sampleRate));
            view.setInt16(offset, sample, true);
            offset += 2;
          }
        }
        var blob = new Blob([buffer], { type: "audio/wav" });
        sirenWavUrl = URL.createObjectURL(blob);
        return sirenWavUrl;
      }

      function ensureSirenAudio() {
        if (!sirenAudio) {
          if (!silentWavUrl) silentWavUrl = buildSilentWavUrl();
          sirenAudio = new Audio(silentWavUrl);
          sirenAudio.loop = false;
          sirenAudio.preload = "auto";
          sirenAudio.setAttribute("playsinline", "true");
          sirenAudio.volume = 1.0;
        }
        return sirenAudio;
      }

      function ensureAudioContext() {
        var Ctx = window.AudioContext || window.webkitAudioContext;
        if (!Ctx) return null;
        if (!audioCtx) audioCtx = new Ctx();
        if (audioCtx.state === "suspended") {
          audioCtx.resume().catch(function () {});
        }
        return audioCtx;
      }

      // Desbloqueo 100% SILENCIOSO para iOS Safari y Chrome Android (NUNCA reproduce la sirena aquí)
      function unlockMobileAudio() {
        try {
          var ctx = ensureAudioContext();
          if (ctx && !audioUnlocked) {
            var silentBuf = ctx.createBuffer(1, 1, 22050);
            var src = ctx.createBufferSource();
            src.buffer = silentBuf;
            src.connect(ctx.destination);
            src.start(0);
          }
        } catch (e) {}
        if (audioUnlocked) return;
        audioUnlocked = true;
        try {
          if (!sirenActive) {
            var a = ensureSirenAudio();
            if (!silentWavUrl) silentWavUrl = buildSilentWavUrl();
            a.loop = false;
            a.src = silentWavUrl;
            a.volume = 0.0;
            var p = a.play();
            if (p && p.then) {
              p.then(function () {
                if (!sirenActive) {
                  a.pause();
                  a.currentTime = 0;
                }
              }).catch(function () {});
            }
          }
        } catch (e) {}
        try {
          if (window.speechSynthesis) {
            window.speechSynthesis.getVoices();
          }
        } catch (e) {}
      }

      ["touchstart", "touchend", "pointerdown", "click"].forEach(function (ev) {
        window.addEventListener(ev, unlockMobileAudio, { passive: true });
      });

      function sendToPython(obj) {
        if (channel) {
          try { channel.postMessage(JSON.stringify(obj)); } catch (e) {}
        }
      }

      function requestBrowserGps() {
        if (!navigator.geolocation) {
          sendToPython({ type: "gps_error", code: "unsupported" });
          return;
        }
        navigator.geolocation.getCurrentPosition(
          function (pos) {
            sendToPython({
              type: "gps_result",
              lat: Number(pos.coords.latitude.toFixed(6)),
              lon: Number(pos.coords.longitude.toFixed(6)),
              acc: Math.round(pos.coords.accuracy || 0)
            });
          },
          function (err) {
            sendToPython({ type: "gps_error", code: err && err.code ? String(err.code) : "denied" });
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
          u.rate = 0.98;
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
        try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch (e) {}
      }

      function stopSiren() {
        sirenActive = false;
        if (sirenAudio) {
          try {
            sirenAudio.pause();
            sirenAudio.loop = false;
            sirenAudio.currentTime = 0;
          } catch (e) {}
        }
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
        sirenActive = true;
        // 1. Reproducir WAV real con HTML5 <audio> (solo cuando el usuario activa la alarma)
        var playedHtmlAudio = false;
        try {
          var a = ensureSirenAudio();
          a.src = buildSirenWavUrl();
          a.loop = true;
          a.muted = false;
          a.volume = 1.0;
          a.currentTime = 0;
          var p = a.play();
          playedHtmlAudio = true;
          if (p && p.catch) {
            p.catch(function () { if (sirenActive) startOscillatorBackup(); });
          }
        } catch (e) {
          playedHtmlAudio = false;
        }
        if (!playedHtmlAudio && sirenActive) {
          startOscillatorBackup();
        }
        if (navigator.vibrate) {
          try { navigator.vibrate([300, 150, 300, 150, 500]); } catch (e) {}
        }
      }

      function startOscillatorBackup() {
        var ctx = ensureAudioContext();
        if (!ctx) return;
        try {
          var freqs = [1200, 820, 1320, 820];
          var idx = 0;
          sirenOsc = ctx.createOscillator();
          sirenGain = ctx.createGain();
          sirenOsc.type = "triangle";
          sirenOsc.frequency.setValueAtTime(freqs[0], ctx.currentTime);
          sirenGain.gain.setValueAtTime(0.5, ctx.currentTime);
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

      if (channel) {
        channel.onmessage = function (evt) {
          var msg = null;
          try { msg = JSON.parse(evt.data); } catch (e) { return; }
          if (!msg || !msg.type) return;
          if (msg.type === "request_gps") {
            requestBrowserGps();
          } else if (msg.type === "speak") {
            speakSpanish(msg.text || "");
          } else if (msg.type === "speak_stop") {
            stopSpeech();
          } else if (msg.type === "siren_start") {
            startSiren();
          } else if (msg.type === "siren_stop") {
            stopSiren();
          } else if (msg.type === "vibrate") {
            if (navigator.vibrate) try { navigator.vibrate([250, 100, 250]); } catch (e) {}
          } else if (msg.type === "unlock_and_test") {
            unlockMobileAudio();
            if (msg.text) speakSpanish(msg.text);
          }
        };
      }
    })();
  </script>
</head>
'@
if ($html -notmatch "map_inclusive_native") {
  $html = $html -replace "</head>", $mobileBridgeScript
  Set-Content -Path $indexPath -Value $html -Encoding UTF8
}

Write-Host "Listo! dist/ generado con BroadcastChannel (iOS/Android GPS + HTML5 WAV Sirena + Voz) en: $distDir" -ForegroundColor Green
