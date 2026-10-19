// Panel siklus: menampilkan state dari SSE, mengunci tombol capture, dan banner pemindai tidak aktif.
(function () {
  "use strict";
  var elStatus = document.getElementById("status-siklus");
  var elDatapart = document.getElementById("info-datapart");
  var tombolCapture = document.getElementById("tombol-capture");
  var tombolReset = document.getElementById("tombol-reset");
  var banner = document.getElementById("banner-pemindai");
  var elGalat = document.getElementById("info-galat-siklus");

  var LABEL = {
    WAIT_DATAPART: "Menunggu datapart…", READY: "Siap — tekan Ambil Gambar",
    CAPTURING: "Mengambil gambar…", INFERRING: "Memproses…", JUDGED: "Menilai…",
    SAVING: "Menyimpan…", PRINTING: "Mencetak…", DONE: "Selesai"
  };

  function render(s) {
    if (elStatus) {
      elStatus.textContent = LABEL[s.state] || s.state;
      elStatus.setAttribute("data-state", s.state); // CSS mewarnai titik status
    }
    if (elDatapart) {
      elDatapart.textContent = s.datapart
        ? s.datapart.kode + " — tipe " + s.datapart.tipe + ", warna " + s.datapart.varian_warna
        : "—";
    }
    if (tombolCapture) { tombolCapture.disabled = s.state !== "READY"; } // terkunci sampai datapart valid
  }

  async function panggil(url) {
    try {
      var resp = await fetch(url, { method: "POST" });
      var data = await resp.json().catch(function () { return {}; });
      if (elGalat) { elGalat.textContent = resp.ok ? "" : (data.pesan || "Permintaan ditolak (HTTP " + resp.status + ")."); }
    } catch (err) {
      console.error(err);
      if (elGalat) { elGalat.textContent = "Server tidak terjangkau."; }
    }
  }

  if (tombolCapture) {
    tombolCapture.addEventListener("click", function () {
      tombolCapture.blur(); // cegah Enter scanner berikutnya "mengklik" tombol lagi
      panggil("/api/cycle/capture");
    });
  }
  if (tombolReset) {
    tombolReset.addEventListener("click", function () { tombolReset.blur(); panggil("/api/cycle/reset"); });
  }

  if (window.CasingSSE) {
    window.CasingSSE.on("state", render);
    window.CasingSSE.on("galat", function (d) { if (elGalat) { elGalat.textContent = d.pesan; } });
  }
  fetch("/api/cycle/state").then(function (r) { return r.json(); }).then(render).catch(function () {});

  // Banner: jendela tidak fokus = scan bisa hilang.
  function periksaFokus() {
    if (!banner) { return; }
    banner.hidden = document.hasFocus() && !document.hidden;
  }
  window.addEventListener("blur", periksaFokus);
  window.addEventListener("focus", periksaFokus);
  document.addEventListener("visibilitychange", periksaFokus);
  setInterval(periksaFokus, 1000);
  periksaFokus();
})();
