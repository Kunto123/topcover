// Layar admin model (CV-9): daftar registri, unggah berprogres, polling job, aktifkan, rollback.
(function () {
  "use strict";
  var U = window.AdminUtil;
  var tbody = document.getElementById("tabel-model");
  var elMesin = document.getElementById("status-mesin");
  var elPesan = document.getElementById("pesan-model");
  var form = document.getElementById("form-impor");
  var elStatus = document.getElementById("status-impor");
  var progres = document.getElementById("progres-impor");

  function tombol(teks, fn) {
    var b = document.createElement("button");
    b.type = "button"; b.className = "tombol"; b.textContent = teks;
    b.addEventListener("click", fn);
    return b;
  }

  async function aktifkan(id) {
    U.pesan(elPesan, "Memuat model…", false);
    try { var d = await U.api("/admin/api/models/" + id + "/aktifkan", { method: "POST" }); U.pesan(elPesan, "Aktif: " + d.versi, false); }
    catch (e) { U.pesan(elPesan, e.message, true); }
    muat();
  }

  async function muat() {
    try {
      var d = await U.api("/admin/api/models");
      var m = d.mesin;
      elMesin.textContent = m.siap ? "Mesin: model " + m.versi + " siap (" + m.device + ")" : "Mesin: GAGAL — " + (m.galat || "belum dimuat");
      elMesin.className = "pesan-admin " + (m.siap ? "ok" : "galat");
      U.kosongkan(tbody);
      d.model.forEach(function (x) {
        var tr = document.createElement("tr");
        [String(x.id), x.versi, x.status, (x.kelas || []).join(", "), x.dibuat_pada].forEach(function (t) { tr.appendChild(U.sel(t)); });
        var aksi = document.createElement("td");
        if (x.status !== "aktif") { aksi.appendChild(tombol("Aktifkan", function () { aktifkan(x.id); })); }
        tr.appendChild(aksi);
        tbody.appendChild(tr);
      });
    } catch (e) { U.pesan(elPesan, e.message, true); }
  }

  document.getElementById("tombol-rollback").addEventListener("click", async function () {
    try { var d = await U.api("/admin/api/models/rollback", { method: "POST" }); U.pesan(elPesan, "Kembali ke: " + d.versi, false); }
    catch (e) { U.pesan(elPesan, e.message, true); }
    muat();
  });

  async function pantau(id) {
    for (var i = 0; i < 1800; i++) {
      var j = await U.api("/admin/api/models/jobs/" + id);
      U.pesan(elStatus, "Status impor: " + j.status + (j.pesan ? " — " + j.pesan : ""), j.status === "gagal");
      if (j.status === "selesai" || j.status === "gagal") { muat(); return; }
      await new Promise(function (r) { setTimeout(r, 1000); });
    }
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var f = form.elements;
    var berkas = f.berkas.files[0];
    if (!berkas) { return; }
    var q = new URLSearchParams({ versi: f.versi.value.trim(), nama_berkas: berkas.name, kelas: f.kelas.value, imgsz: f.imgsz.value, aktifkan: f.aktifkan.checked ? "true" : "false" });
    var xhr = new XMLHttpRequest();
    xhr.open("PUT", "/admin/api/models/unggah?" + q.toString());
    progres.hidden = false;
    xhr.upload.onprogress = function (e) { if (e.lengthComputable) { progres.value = Math.round(100 * e.loaded / e.total); } };
    xhr.onload = function () {
      progres.hidden = true;
      var data = {};
      try { data = JSON.parse(xhr.responseText); } catch (e) { data = {}; }
      if (xhr.status === 401) { window.location.href = "/login"; return; }
      if (xhr.status === 202) { pantau(data.job_id).catch(function (e) { U.pesan(elStatus, e.message, true); }); }
      else { U.pesan(elStatus, typeof data.detail === "string" ? data.detail : "Unggah gagal (HTTP " + xhr.status + ").", true); }
    };
    xhr.onerror = function () { progres.hidden = true; U.pesan(elStatus, "Server tidak terjangkau.", true); };
    xhr.send(berkas);
  });
  muat();
})();
