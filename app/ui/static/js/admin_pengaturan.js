// Layar admin pengaturan (CV-10).
(function () {
  "use strict";
  var U = window.AdminUtil;
  var form = document.getElementById("form-pengaturan");
  var elPesan = document.getElementById("pesan-pengaturan");
  var elVersi = document.getElementById("versi-pengaturan");
  var elWarn = document.getElementById("peringatan-pengaturan");
  var elRiwayat = document.getElementById("riwayat-pengaturan");
  var DEFAULT = { ambang_keyakinan: 0.8, masa_simpan_gambar_hari: 3, ruang_warna: "lab", jumlah_part_default: 6, izinkan_kurang_dari_default: false };

  function isi(d) {
    var f = form.elements;
    f.ambang.value = Math.round(d.ambang_keyakinan * 100);
    f.masa.value = d.masa_simpan_gambar_hari; f.ruang.value = d.ruang_warna;
    f.jumlah.value = d.jumlah_part_default; f.kurang.checked = d.izinkan_kurang_dari_default;
  }
  function tampilWarn(daftar) {
    U.kosongkan(elWarn);
    (daftar || []).forEach(function (t) { var p = document.createElement("p"); p.className = "peringatan-admin"; p.textContent = "Peringatan: " + t; elWarn.appendChild(p); });
  }
  async function muat() {
    try {
      var d = await U.api("/admin/api/pengaturan");
      isi(d.data); elVersi.textContent = "Versi konfigurasi: " + d.versi;
      U.kosongkan(elRiwayat);
      d.riwayat.forEach(function (r) {
        var li = document.createElement("li");
        li.textContent = r.waktu + " — " + r.oleh + " (v" + r.versi + "): " + Object.keys(r.diff).join(", ");
        elRiwayat.appendChild(li);
      });
    } catch (e) { U.pesan(elPesan, e.message, true); }
  }
  document.getElementById("tombol-default").addEventListener("click", function () { isi(DEFAULT); });
  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var f = form.elements;
    try {
      var d = await U.api("/admin/api/pengaturan", U.json("PUT", {
        ambang_keyakinan: parseFloat(f.ambang.value) / 100, masa_simpan_gambar_hari: parseInt(f.masa.value, 10),
        ruang_warna: f.ruang.value, jumlah_part_default: parseInt(f.jumlah.value, 10), izinkan_kurang_dari_default: f.kurang.checked
      }));
      U.pesan(elPesan, d.berubah ? "Tersimpan (versi " + d.versi + ")." : "Tidak ada perubahan.", false);
      tampilWarn(d.peringatan); muat();
    } catch (e) { U.pesan(elPesan, e.message, true); }
  });
  muat();
})();