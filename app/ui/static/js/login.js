// Bar sesi + form login (CV-5). Teks dari server hanya lewat textContent.
(function () {
  "use strict";
  var elNama = document.getElementById("sesi-nama");
  var elMasuk = document.getElementById("sesi-masuk");
  var elKeluar = document.getElementById("sesi-keluar");
  var elAdmin = document.getElementById("sesi-admin");
  var panel = document.getElementById("panel-login");
  var form = document.getElementById("form-login");
  var elInfo = document.getElementById("info-login");

  function tampilkan(s) {
    var login = !!(s && s.login);
    if (elNama) { elNama.textContent = login ? s.nama + " (" + s.peran + ")" : "Belum login"; }
    if (elMasuk) { elMasuk.hidden = login; }
    if (elKeluar) { elKeluar.hidden = !login; }
    if (elAdmin) { elAdmin.hidden = !(login && s.peran === "admin"); }
    if (panel) { panel.hidden = login; }
  }

  function muat() {
    fetch("/api/auth/sesi").then(function (r) { return r.json(); }).then(tampilkan).catch(function () {});
  }

  if (elKeluar) {
    elKeluar.addEventListener("click", function () {
      fetch("/api/auth/logout", { method: "POST" }).then(muat).catch(function () {});
    });
  }

  if (form) {
    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      if (elInfo) { elInfo.textContent = ""; }
      try {
        var resp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            username: form.elements.username.value,
            password: form.elements.password.value
          })
        });
        var data = await resp.json().catch(function () { return {}; });
        form.elements.password.value = "";
        if (resp.ok) { window.location.href = "/"; return; }
        if (elInfo) { elInfo.textContent = data.pesan || "Login gagal (HTTP " + resp.status + ")."; }
      } catch (err) {
        console.error(err);
        if (elInfo) { elInfo.textContent = "Server tidak terjangkau."; }
      }
    });
  }

  // Hasil login RFID datang lewat respons scan (event dari scan_capture.js).
  document.addEventListener("casing:scan", function (e) {
    var d = e.detail && e.detail.data;
    var info = document.getElementById("info-rfid");
    if (!d || d.hasil !== "rfid" || !d.login || !info) { return; }
    info.textContent = d.login.sukses ? "Masuk: " + d.login.nama : d.login.pesan;
  });

  if (window.CasingSSE) { window.CasingSSE.on("sesi", tampilkan); }
  muat();
  setInterval(muat, 30000); // sesi bisa berakhir karena idle tanpa ada event
})();
