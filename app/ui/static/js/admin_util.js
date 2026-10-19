// Util bersama layar admin: fetch JSON dengan penanganan 401/403/422. Teks hanya via textContent.
window.AdminUtil = (function () {
  "use strict";
  function pesanGalat(data, status) {
    if (data && typeof data.detail === "string") { return data.detail; }
    if (data && Array.isArray(data.detail) && data.detail.length) {
      return data.detail.map(function (d) { return (d.loc ? d.loc.slice(1).join(".") + ": " : "") + d.msg; }).join("; ");
    }
    if (data && data.pesan) { return data.pesan; }
    return "Permintaan gagal (HTTP " + status + ").";
  }
  async function api(url, opsi) {
    var resp = await fetch(url, opsi || {});
    var data = await resp.json().catch(function () { return {}; });
    if (resp.status === 401) { window.location.href = "/login"; throw new Error("belum login"); }
    if (!resp.ok) { var e = new Error(pesanGalat(data, resp.status)); e.status = resp.status; throw e; }
    return data;
  }
  function json(metode, badan) {
    return { method: metode, headers: { "Content-Type": "application/json" }, body: JSON.stringify(badan) };
  }
  function pesan(el, teks, galat) {
    if (!el) { return; }
    el.textContent = teks || "";
    el.className = "pesan-admin " + (teks ? (galat ? "galat" : "ok") : "");
  }
  function sel(teks) { var td = document.createElement("td"); td.textContent = teks; return td; }
  function kosongkan(el) { while (el.firstChild) { el.removeChild(el.firstChild); } }
  return { api: api, json: json, pesan: pesan, sel: sel, kosongkan: kosongkan };
})();