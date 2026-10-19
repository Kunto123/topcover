// Klien SSE ringan: status koneksi + pendaftaran pendengar event (window.CasingSSE.on).
(function () {
  var penanda = document.getElementById("status-sse");
  var antre = []; // pendengar yang didaftarkan sebelum EventSource siap
  var sumber = null;

  window.CasingSSE = {
    // Daftarkan fn(data) untuk event bernama `nama`; data sudah di-parse dari JSON.
    on: function (nama, fn) {
      var bungkus = function (e) {
        try { fn(JSON.parse(e.data)); } catch (err) { console.error("SSE data rusak", nama, err); }
      };
      if (sumber) { sumber.addEventListener(nama, bungkus); } else { antre.push([nama, bungkus]); }
    }
  };

  if (!window.EventSource) { return; }

  function tampil(terhubung) {
    if (!penanda) { return; }
    penanda.textContent = terhubung ? "SSE: terhubung" : "SSE: terputus";
    penanda.className = "status " + (terhubung ? "status-ok" : "status-putus");
  }

  sumber = new EventSource("/events");
  sumber.onopen = function () { tampil(true); };
  sumber.onerror = function (e) {
    tampil(false);
    console.error("SSE error", e); // EventSource menyambung ulang otomatis
  };
  antre.forEach(function (p) { sumber.addEventListener(p[0], p[1]); });
  antre = [];
})();
