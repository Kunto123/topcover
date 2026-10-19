-- Varian warna datapart pada hasil (CV-0c); untuk metrik per varian (CV-14). Baris lama NULL.
ALTER TABLE hasil_pemeriksaan ADD COLUMN varian_warna text;
CREATE INDEX hasil_varian_waktu_idx ON hasil_pemeriksaan (varian_warna, waktu_selesai);
