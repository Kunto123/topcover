// Klien SSE ringan: menampilkan status koneksi; event siklus ditambahkan oleh CV-6/CV-12.
(function () {
  var penanda = document.getElementById("status-sse");
  if (!penanda || !window.EventSource) { return; }

  function tampil(terhubung) {
    penanda.textContent = terhubung ? "SSE: terhubung" : "SSE: terputus";
    penanda.className = "status " + (terhubung ? "status-ok" : "status-putus");
  }

  var sumber = new EventSource("/events");
  sumber.onopen = function () { tampil(true); };
  sumber.onerror = function (e) {
    tampil(false);
    console.error("SSE error", e); // EventSource menyambung ulang otomatis
  };
})();
