// Layar admin varian warna (CV-10).
(function () {
  "use strict";
  var U = window.AdminUtil;
  var tbody = document.getElementById("tabel-warna");
  var kotakPeringatan = document.getElementById("peringatan-warna");
  var form = document.getElementById("form-warna");
  var elPesan = document.getElementById("pesan-warna");

  function tombol(teks, fn) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "tombol"; b.textContent = teks;
    b.addEventListener("click", fn);
    return b;
  }

  async function ubahAktif(nama, aktif) {
    try {
      await U.api("/admin/api/warna/" + encodeURIComponent(nama) + (aktif ? "/aktifkan" : "/nonaktifkan"), { method: "POST" });
      muat();
    } catch (e) { U.pesan(elPesan, e.message, true); }
  }

  function isiForm(v) {
    form.elements.nama.value = v.nama;
    form.elements.a.value = v.referensi[0]; form.elements.b.value = v.referensi[1]; form.elements.c.value = v.referensi[2];
    form.elements.toleransi.value = v.toleransi; form.elements.ruang.value = v.ruang;
  }

  async function muat() {
    try {
      var d = await U.api("/admin/api/warna?semua=true");
      U.kosongkan(tbody);
      d.varian.forEach(function (v) {
        var tr = document.createElement("tr");
        [v.nama, v.ruang, v.referensi.join(", "), String(v.toleransi), v.aktif ? "aktif" : "nonaktif", "v" + v.versi]
          .forEach(function (t) { tr.appendChild(U.sel(t)); });
        var aksi = document.createElement("td");
        aksi.appendChild(tombol("Ubah", function () { isiForm(v); }));
        aksi.appendChild(tombol(v.aktif ? "Nonaktifkan" : "Aktifkan", function () { ubahAktif(v.nama, !v.aktif); }));
        tr.appendChild(aksi);
        tbody.appendChild(tr);
      });
      tampilPeringatan(d.peringatan);
    } catch (e) { U.pesan(elPesan, e.message, true); }
  }

  function tampilPeringatan(daftar) {
    U.kosongkan(kotakPeringatan);
    (daftar || []).forEach(function (p) {
      var el = document.createElement("p");
      el.className = "peringatan-admin";
      el.textContent = "Peringatan: toleransi '" + p.a + "' dan '" + p.b + "' (" + p.ruang + ") tumpang tindih — jarak " +
        p.jarak + " <= jumlah toleransi " + p.jumlah_toleransi + ". Box warna lain bisa lolos.";
      kotakPeringatan.appendChild(el);
    });
  }

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var f = form.elements;
    try {
      var d = await U.api("/admin/api/warna/" + encodeURIComponent(f.nama.value.trim()), U.json("PUT", {
        referensi: [parseFloat(f.a.value), parseFloat(f.b.value), parseFloat(f.c.value)],
        toleransi: parseFloat(f.toleransi.value), ruang: f.ruang.value
      }));
      U.pesan(elPesan, "Tersimpan (versi " + d.versi + ").", false);
      tampilPeringatan(d.peringatan);
      muat();
    } catch (e) { U.pesan(elPesan, e.message, true); }
  });
  muat();
})();