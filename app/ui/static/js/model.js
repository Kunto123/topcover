// Status model inferensi (CV-8). Teks dari server hanya lewat textContent.
(function () {
  "use strict";
  var el = document.getElementById("status-model");
  if (!el) { return; }

  function tampil(s) {
    if (s.siap) {
      el.textContent = "Model: " + s.versi + " · " + s.device + " · siap";
      el.className = "status-model status-model-ok";
    } else {
      el.textContent = "Model: GAGAL — " + (s.galat || "belum dimuat");
      el.className = "status-model status-model-gagal";
    }
  }

  function muat() {
    fetch("/api/inference/status").then(function (r) { return r.json(); }).then(tampil)
      .catch(function () {
        el.textContent = "Model: status tidak terbaca";
        el.className = "status-model status-model-gagal";
      });
  }

  muat();
  setInterval(muat, 15000);
})();
