// Penangkap scanner/RFID (keyboard-wedge) global tanpa kolom input.
// Logika klasifikasi (buatPenangkap) murni agar bisa diuji dengan Node; lapisan DOM di bawahnya.
(function (root) {
  "use strict";

  // opsi: {intervalMs, minPanjang, idleFlushMs, terminator}. Waktu `t` dalam milidetik.
  function buatPenangkap(opsi) {
    var intervalMs = opsi.intervalMs;
    var minPanjang = opsi.minPanjang;
    var idleFlushMs = opsi.idleFlushMs;
    var terminator = opsi.terminator || ["Enter", "Tab"];
    var buffer = "";
    var terakhir = null;

    function reset() { buffer = ""; terakhir = null; }

    return {
      // Kembalikan null (bukan urusan scanner) atau {kode, cegah}; kode null = belum selesai.
      tekan: function (ev, t) {
        if (ev.ctrlKey || ev.altKey || ev.metaKey) { return null; }
        if (ev.targetEditable) { reset(); return null; } // login manual didahulukan
        var key = ev.key;
        if (typeof key === "string" && key.length === 1) {
          if (buffer.length > 0 && t - terakhir > intervalMs) { reset(); } // ketikan lambat = manusia
          buffer += key;
          terakhir = t;
          return { kode: null, cegah: buffer.length >= 2 };
        }
        if (terminator.indexOf(key) >= 0) {
          var cukup = buffer.length >= minPanjang && terakhir !== null && t - terakhir <= idleFlushMs;
          var kode = cukup ? buffer : null;
          var ada = buffer.length > 0;
          reset();
          if (kode) { return { kode: kode, cegah: true }; }
          return ada ? { kode: null, cegah: false } : null;
        }
        return null;
      },
      // Buang buffer yang menggantung terlalu lama tanpa terminator.
      idleFlush: function (t) {
        if (buffer.length > 0 && t - terakhir > idleFlushMs) { reset(); }
      },
      isi: function () { return buffer; }
    };
  }

  var api = { buatPenangkap: buatPenangkap };
  root.CasingScan = api;
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }

  if (typeof document === "undefined") { return; }

  // ---- Lapisan DOM ----
  var konfig = { intervalMs: 50, minPanjang: 3, idleFlushMs: 150 };
  var elKonfig = document.getElementById("konfig-scan");
  if (elKonfig) {
    try { konfig = Object.assign(konfig, JSON.parse(elKonfig.textContent)); } catch (e) { console.error(e); }
  }
  var penangkap = buatPenangkap(konfig);
  var antrean = [];
  var berjalan = false;

  function info(teks, galat) {
    var el = document.getElementById("info-scan");
    if (!el) { return; }
    el.textContent = teks;
    el.className = "info-scan " + (galat ? "info-galat" : "info-ok");
  }

  function editable(el) {
    if (!el) { return false; }
    var tag = (el.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable === true;
  }

  async function kirimBerikut() {
    if (berjalan) { return; }
    berjalan = true;
    while (antrean.length > 0) {
      var kode = antrean.shift();
      try {
        var resp = await fetch("/api/cycle/scan", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kode: kode })
        });
        var data = await resp.json().catch(function () { return {}; });
        if (resp.ok) {
          info(data.hasil === "rfid" ? "Kartu RFID diterima." : "Datapart diterima: " + kode, false);
        } else if (resp.status === 409) {
          info("Siklus masih berjalan; scan diabaikan.", true);
        } else if (resp.status === 422) {
          info("Datapart tidak valid: " + (data.pesan || kode), true);
        } else {
          info("Scan gagal diproses (HTTP " + resp.status + ").", true);
        }
        document.dispatchEvent(new CustomEvent("casing:scan", { detail: { kode: kode, status: resp.status, data: data } }));
      } catch (err) {
        console.error("scan gagal dikirim", err);
        info("Scan tidak terkirim (server tidak terjangkau). Ulangi scan.", true);
      }
    }
    berjalan = false;
  }

  document.addEventListener("keydown", function (ev) {
    var hasil = penangkap.tekan({
      key: ev.key, ctrlKey: ev.ctrlKey, altKey: ev.altKey, metaKey: ev.metaKey,
      targetEditable: editable(ev.target)
    }, performance.now());
    if (!hasil) { return; }
    if (hasil.cegah) { ev.preventDefault(); ev.stopPropagation(); }
    if (hasil.kode) { antrean.push(hasil.kode); kirimBerikut(); }
  }, true);

  setInterval(function () { penangkap.idleFlush(performance.now()); }, 100);
})(typeof window !== "undefined" ? window : globalThis);
