// Panel hasil operator (CV-12): MATCH/NOT_MATCH, alasan, rincian part, waktu, counter.
// Semua teks dari server lewat textContent (bukan innerHTML).
(function () {
  "use strict";
  var panel = document.getElementById("panel-hasil");
  if (!panel) { return; }
  var elBadge = document.getElementById("hasil-badge");
  var elPesan = document.getElementById("hasil-pesan");
  var elPeringatan = document.getElementById("hasil-peringatan");
  var elTabel = document.getElementById("hasil-rincian");
  var elWaktu = document.getElementById("hasil-waktu");
  var elCounter = document.getElementById("hasil-counter");
  var cycleTampil = null;

  var PERINGATAN = {
    gagal_push: "Push database gagal — ulangi siklus.",
    simpan_lokal_gagal: "Simpan lokal gagal — ulangi siklus.",
    tidak_dikonfigurasi: "Database pabrik belum dikonfigurasi — hasil tidak tersimpan.",
    lokal_gagal_setelah_push: "Tersimpan di pabrik, gagal lokal — JANGAN ulangi, panggil SPV.",
    gagal_cetak: "Cetak gagal (data tersimpan) — hubungi teknisi.",
    galat_internal: "Galat internal — periksa log."
  };

  function sel(teks) {
    var td = document.createElement("td");
    td.textContent = teks;
    return td;
  }

  function persen(x) { return x === null || x === undefined ? "—" : Math.round(x * 100) + "%"; }

  function tampil(h) {
    if (!h || !h.verdict) { panel.hidden = true; return; }
    cycleTampil = h.cycle_id;
    panel.hidden = false;
    var match = h.verdict === "match";
    elBadge.textContent = match ? "MATCH" : "NOT MATCH";
    elBadge.className = "hasil-badge " + (match ? "hasil-match" : "hasil-notmatch");
    elPesan.textContent = h.pesan || "";
    var peringatan = PERINGATAN[h.status];
    elPeringatan.textContent = peringatan || "";
    elPeringatan.hidden = !peringatan;
    while (elTabel.firstChild) { elTabel.removeChild(elTabel.firstChild); }
    (h.rincian || []).forEach(function (r, i) {
      var tr = document.createElement("tr");
      tr.appendChild(sel(String(i + 1)));
      tr.appendChild(sel(r.kelas));
      tr.appendChild(sel(persen(r.keyakinan)));
      tr.appendChild(sel(r.jarak === null || r.jarak === undefined ? "—" : String(r.jarak)));
      elTabel.appendChild(tr);
    });
    if (h.total_ms !== null && h.total_ms !== undefined) {
      var detik = (h.total_ms / 1000).toFixed(1);
      elWaktu.textContent = "Waktu siklus: " + detik + " detik" + (h.lewat_10_detik ? " (melebihi 10 detik)" : "");
      elWaktu.className = "hasil-waktu" + (h.lewat_10_detik ? " hasil-lambat" : "");
    } else {
      elWaktu.textContent = "";
    }
    if (h.counter && h.counter.match_hari_ini !== undefined) {
      elCounter.textContent = "MATCH hari ini: " + h.counter.match_hari_ini;
    }
  }

  function muatCounter() {
    fetch("/api/cycle/counter").then(function (r) { return r.ok ? r.json() : null; }).then(function (c) {
      if (c && elCounter) { elCounter.textContent = "MATCH hari ini: " + c.match_hari_ini; }
    }).catch(function () {});
  }

  if (window.CasingSSE) {
    window.CasingSSE.on("hasil", tampil);
    window.CasingSSE.on("state", function (s) {
      // siklus baru dimulai: sembunyikan hasil lama
      if (s.state === "READY" && s.cycle_id && s.cycle_id !== cycleTampil) { panel.hidden = true; }
    });
  }
  fetch("/api/cycle/hasil").then(function (r) { return r.json(); }).then(tampil).catch(function () {});
  muatCounter();
})();