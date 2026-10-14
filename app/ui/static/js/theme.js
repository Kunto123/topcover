// Tema light/dark. Pilihan disimpan di localStorage (dibungkus try/catch: bisa gagal di mode privat).
(function () {
  var KUNCI = "casing-tema";
  var root = document.documentElement;

  function baca() {
    try { return window.localStorage.getItem(KUNCI); } catch (e) { return null; }
  }

  function simpan(nilai) {
    try { window.localStorage.setItem(KUNCI, nilai); } catch (e) { /* abaikan */ }
  }

  function efektif() {
    var dipilih = root.getAttribute("data-theme");
    if (dipilih) { return dipilih; }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  }

  // Terapkan sebelum paint agar tidak berkedip.
  var tersimpan = baca();
  if (tersimpan === "light" || tersimpan === "dark") {
    root.setAttribute("data-theme", tersimpan);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tombol = document.getElementById("tombol-tema");
    if (!tombol) { return; }
    tombol.addEventListener("click", function () {
      var berikut = efektif() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", berikut);
      simpan(berikut);
    });
  });
})();
