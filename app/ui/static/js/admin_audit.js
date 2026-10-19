// Layar admin audit SPV (CV-14). Teks server hanya lewat textContent.
(function () {
  "use strict";
  var U = window.AdminUtil;
  var form = document.getElementById("form-audit");
  var elPesan = document.getElementById("pesan-audit");
  var tbody = document.getElementById("tabel-audit");
  var elSeed = document.getElementById("info-seed");
  var ringkas = document.getElementById("ringkasan-audit");
  var rincian = document.getElementById("rincian-audit");

  function hariIni() { var d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); }
  form.elements.mulai.value = hariIni(); form.elements.sampai.value = hariIni();

  function parameter() {
    var f = form.elements;
    var q = new URLSearchParams({ mulai: f.mulai.value, sampai: f.sampai.value, sampel_match: f.sampel.value || "0" });
    if (f.varian.value.trim()) { q.set("varian", f.varian.value.trim()); }
    if (f.seed.value.trim()) { q.set("seed", f.seed.value.trim()); }
    return q;
  }

  function item(teks) { var li = document.createElement("li"); li.textContent = teks; ringkas.appendChild(li); }

  async function muatRingkasan() {
    var q = parameter(); q.delete("sampel_match"); q.delete("varian"); q.delete("seed");
    var r = await U.api("/admin/api/audit/ringkasan?" + q.toString());
    U.kosongkan(ringkas);
    item("Total " + r.total + " — MATCH " + r.match + ", NOT_MATCH " + r.not_match + (r.persen_match === null ? "" : " (" + r.persen_match + "% MATCH)"));
    var d = r.durasi;
    item("Siklus ≤ 10 detik: " + (d.persen_dalam_10_detik === null ? "—" : d.persen_dalam_10_detik + "%") + " dari " + d.n + " (p50 " + d.p50_ms + " ms, p95 " + d.p95_ms + " ms; tanpa durasi: " + d.tanpa_durasi + ")");
    Object.keys(r.per_alasan).forEach(function (k) { item("Alasan " + k + ": " + r.per_alasan[k]); });
    r.per_varian.forEach(function (v) { item("Varian " + v.varian + ": MATCH " + v.match + ", NOT_MATCH " + v.not_match); });
    Object.keys(r.rata_tahap_ms).forEach(function (k) { item("Rata-rata " + k + ": " + r.rata_tahap_ms[k] + " ms"); });
  }

  function tampilRincian(b) {
    rincian.hidden = false;
    document.getElementById("judul-rincian").textContent = b.cycle_id + " — " + b.datapart;
    var tb = document.getElementById("part-rincian"); U.kosongkan(tb);
    (b.detail_part || []).forEach(function (p, i) {
      var tr = document.createElement("tr");
      [String(i + 1), p.kelas, Math.round(p.keyakinan * 100) + "%", p.jarak === null ? "—" : String(p.jarak), p.ruang_warna].forEach(function (t) { tr.appendChild(U.sel(t)); });
      tb.appendChild(tr);
    });
    var img = document.getElementById("gambar-rincian"), info = document.getElementById("info-gambar");
    if (b.gambar_url) { img.src = b.gambar_url; img.hidden = false; info.textContent = ""; }
    else { img.hidden = true; img.removeAttribute("src"); info.textContent = b.gambar_dibersihkan ? "Gambar sudah dibersihkan (masa simpan habis)." : "Tidak ada gambar."; }
  }

  async function muat() {
    try {
      var d = await U.api("/admin/api/audit?" + parameter().toString());
      elSeed.textContent = "Seed sampel: " + d.seed + (d.terpotong ? " — daftar NOT_MATCH dipotong." : "");
      form.elements.seed.value = d.seed;
      U.kosongkan(tbody);
      d.baris.forEach(function (b) {
        var tr = document.createElement("tr");
        [b.waktu_selesai, b.datapart, b.verdict === "match" ? "MATCH" : "NOT MATCH", b.alasan_teks || "—", b.operator, b.durasi_ms === null ? "—" : (b.durasi_ms / 1000).toFixed(1) + " s"].forEach(function (t) { tr.appendChild(U.sel(t)); });
        var aksi = document.createElement("td");
        var tombol = document.createElement("button"); tombol.type = "button"; tombol.className = "tombol"; tombol.textContent = "Rincian";
        tombol.addEventListener("click", function () { tampilRincian(b); });
        aksi.appendChild(tombol); tr.appendChild(aksi); tbody.appendChild(tr);
      });
      U.pesan(elPesan, d.baris.length + " baris.", false);
      await muatRingkasan();
    } catch (e) { U.pesan(elPesan, e.message, true); }
  }

  form.addEventListener("submit", function (ev) { ev.preventDefault(); if (!ev.submitter || ev.submitter.id !== "tombol-csv") { form.elements.seed.value = form.elements.seed.value; } muat(); });
  document.getElementById("tombol-csv").addEventListener("click", function () {
    window.location.href = "/admin/api/audit/export.csv?" + parameter().toString();
  });
  muat();
})();
