// Panel kamera: preview MJPEG + status (polling /api/camera/status tiap 2 detik).
(function () {
  "use strict";
  var img = document.getElementById("preview-kamera");
  var elStatus = document.getElementById("status-kamera");
  if (!img || !elStatus) { return; }
  var aliranDimuat = false;

  function setStatus(teks, galat) {
    elStatus.textContent = teks;
    elStatus.className = "status-kamera " + (galat ? "status-kamera-galat" : "status-kamera-ok");
  }

  function muatAliran() {
    img.src = "/camera/stream?t=" + Date.now(); // parameter waktu mencegah cache aliran lama
    img.hidden = false;
    aliranDimuat = true;
  }

  img.addEventListener("error", function () {
    aliranDimuat = false;
    setTimeout(function () { if (!img.hidden) { muatAliran(); } }, 2000); // sambung ulang
  });

  async function periksa() {
    try {
      var resp = await fetch("/api/camera/status");
      var s = await resp.json();
      if (!s.aktif) {
        img.hidden = true; aliranDimuat = false;
        setStatus("Kamera dimatikan (CASING_CAMERA_ENABLED=false).", true);
        return;
      }
      if (!aliranDimuat) { muatAliran(); }
      if (s.terhubung) {
        var res = s.resolusi ? s.resolusi[0] + "x" + s.resolusi[1] : "?";
        setStatus("Kamera: terhubung · " + Math.round(s.fps) + " fps · " + res, false);
      } else {
        setStatus("KAMERA TIDAK TERSEDIA — " + (s.galat_terakhir || "belum terhubung"), true);
      }
    } catch (err) {
      console.error(err);
      setStatus("Server tidak merespons.", true);
    }
  }

  periksa();
  setInterval(periksa, 2000);
})();
