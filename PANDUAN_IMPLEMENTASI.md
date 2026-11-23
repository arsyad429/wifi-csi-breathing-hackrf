# Langkah penyelesaian studi kasus Case B

Contoh shell di halaman ini memakai **Linux/macOS (Bash/Zsh)**. Versi lengkap **Windows PowerShell** untuk setiap tahap ada di [WINDOWS.md](WINDOWS.md); ringkasan dua OS juga tersedia di [README.md](README.md). Perintah `python case_b.py ...` identik setelah `.venv` diaktifkan pada OS masing-masing.

## 0. Peta pengerjaan: setiap tahap untuk apa?

Urutan ini membantu membedakan pekerjaan operator, fungsi skrip, dan bukti yang perlu disimpan. Jangan langsung menjalankan evaluasi sebelum ada rekaman, metadata final, dan hitungan napas aktual.

| Urutan | Tujuan: mengapa dilakukan? | Tindakan: apa yang dikerjakan? | Keluaran dan keputusan berikutnya |
| --- | --- | --- | --- |
| 1. Siapkan Python | Menyediakan paket yang dibutuhkan tanpa mencampurnya dengan proyek lain. | Buat `.venv`, aktifkan atau panggil interpreter-nya langsung, lalu pasang `requirements.txt`. | Interpreter proyek dapat mengimpor NumPy, SciPy, pandas, dan matplotlib. Lanjutkan pemeriksaan software. |
| 2. Periksa software | Memisahkan masalah instalasi/kode dari masalah radio atau geometri eksperimen. | Jalankan `doctor`, `selftest`, lalu `demo`. | Lihat `doctor.json`, `tests.txt`, dan demo bertanda sintetis. Lulus demo belum berarti HackRF siap atau napas berhasil diukur. |
| 3. Siapkan eksperimen | Membuat perbandingan antarsesi mempunyai kondisi dan label yang dapat ditelusuri. | Tetapkan kanal/gain, tandai posisi perangkat, buat jadwal dengan `plan`, dan siapkan metadata tiap trial. | Jadwal, denah, serta file metadata tersedia sebelum capture. |
| 4. Uji pilot | Memastikan sinyal benar-benar dapat menghasilkan CSI sebelum menghabiskan waktu dan disk pada trial utama. | Rekam singkat, periksa paket/gap/clipping, dan validasi asal pemancar. | Jika QC belum lolos, perbaiki kanal, gain, trafik, atau posisi, lalu ulang pilot. |
| 5. Rekam trial | Mengambil sinyal fisik yang dipengaruhi napas dengan kondisi yang tercatat. | Jalankan `record` saat subjek mengikuti protokol; pengamat menghitung napas aktual dan mencatat gerak. | Raw `.cs8`, CSI, QC, dan catatan pengamat. Ini tahap yang benar-benar membutuhkan HackRF. |
| 6. Lengkapi ground truth | Menyediakan nilai pembanding yang benar untuk menghitung galat prediksi. | Salin metadata hasil run ke file `.final.json`, isi hitungan napas aktual, dan pertahankan blok QC. | Metadata final mempunyai GT berdasarkan hitungan, bukan hanya target metronom. |
| 7. Periksa satu trial | Melihat apakah variasi amplitudo dan puncak spektral masuk akal sebelum evaluasi banyak trial. | Jalankan `analyze`; periksa amplitudo, FFT, confidence, dan alasan penolakan. | Grafik serta prediksi satu trial. Hasil ini belum menggantikan evaluasi sesi uji. |
| 8. Susun dataset | Menghubungkan tiap file CSI dengan subjek, sesi, skenario, dan GT yang benar. | Isi `data/dataset.csv` dengan path CSI dan metadata final seluruh trial. | Daftar trial siap dievaluasi; satu sesi fisik tidak boleh dipecah menjadi identitas sesi baru. |
| 9. Evaluasi | Mengukur kemampuan pada sesi/orang yang tidak dipakai memilih carrier dan membandingkan CSI dengan RSSI. | Jalankan `evaluate --split session`, lalu opsional `--split person`. | MAE, bias, coverage, QC, dan audit fold; baca semuanya sebelum menilai hipotesis. |
| 10. Arsipkan dan laporkan | Membuat hasil bisa diperiksa dan dijalankan ulang, termasuk trial yang gagal. | Simpan metadata, raw contoh, snapshot versi, tabel/grafik, dan alasan kegagalan; susun laporan/presentasi. | Paket luaran studi kasus berdasarkan pengukuran nyata. |

`record` dan `extract` adalah dua pintu masuk alternatif. `record` merekam dari HackRF **dan langsung mengekstrak CSI**. `extract` dipakai jika sudah mempunyai raw `.cs8`, sehingga tidak perlu merekam ulang. Setelah keduanya, alur berikutnya sama: metadata final → `analyze` → daftar dataset → `evaluate`.

## 1. Tujuan dan batas hasil

Pertanyaan utama: seberapa akurat laju napas 10, 15, dan 20 BPM diperkirakan dari amplitudo CSI, dan bagaimana galatnya dibandingkan RSSI pada rekaman yang sama?

Rujukan utama adalah [rancangan kelompok](https://docs.google.com/document/d/1Dq9eeTyFWjOBS815AwdrJpM95OYRrlaCPmg5FooycJE/edit) dan `case_base_csi_sdr.pdf` bagian 3, Case B pada bagian 4, serta bagian 6–10. Pola CLI, pembacaan signed int8 I/Q, dan petunjuk praktikum merujuk repo lokal `../LoRa_SDR` dan `../untuk_mahasiswa`. Modem LoRa tidak dipakai untuk mengekstrak Wi-Fi CSI.

Hipotesis yang diuji:

1. MAE CSI lebih kecil daripada RSSI pada sesi uji terpisah.
2. MAE CSI mencapai ≤3 BPM pada kondisi subjek diam; ini **target usulan**, bukan jaminan hasil.
3. Pemilihan carrier dari sesi latih lebih baik daripada baseline carrier tetap; hasil negatif juga dilaporkan.

Skrip dan data sintetis menguji pipeline. Data radio serta ground truth manusia tetap harus diambil untuk menjawab hipotesis. Jangan menyalin metrik demo sebagai hasil eksperimen.

## 2. Persiapan perangkat dan lingkungan

**Tujuan:** memastikan software siap, radio menerima kanal yang benar, dan perubahan hasil antarsesi tidak semata-mata berasal dari perpindahan posisi, gain, atau kondisi ruangan.

1. Buat `.venv`, aktifkan, lalu pasang `requirements.txt` sesuai README. Jalankan `doctor`, `selftest`, dan `demo`.
2. Pasang antena 5 GHz pada HackRF One. Pastikan `hackrf_info` menemukan perangkat dan kabel USB mampu mempertahankan 20 Msps.
3. Gunakan router milik kelompok pada primary channel **36 = 5180 MHz, lebar 20 MHz**. Matikan pemindahan kanal otomatis bila perangkat mengizinkan. Periksa kembali sebelum setiap sesi. Jangan memakai frekuensi tengah kanal 40/80 MHz.
4. Letakkan router dan HackRF setinggi sekitar 1 m, berjarak 3–5 m. Tandai tempat antena dan kursi. Subjek berada 1–2 m dari garis LOS; catat ukuran sebenarnya dalam denah.
5. Catat ruangan, pintu, furnitur, orang lain, orientasi badan, dan posisi kabel/antena. Jaga tetap sepanjang sesi pembanding.
6. Siapkan ruang disk. Pada 20 Msps, `.cs8` memakai 40 MB/s; 60 detik sekitar **2,4 GB**. Sebanyak 27 trial utama sekitar 64,8 GB, belum termasuk kontrol.
7. Minta persetujuan tertulis dan gunakan ID P1–P3. Rekam hanya di ruangan yang diizinkan. HackRF RX-only; payload pihak lain tidak dibaca. Subjek boleh berhenti kapan saja.

Frekuensi/gain awal disediakan di `config/default.json`: LNA 40 dB, VGA 26 dB, amplifier OFF. Sesuaikan setelah pilot, lalu bekukan konfigurasi sebelum trial pembanding dan evaluasi uji. Untuk kanal lain, ubah `channel` dan `center_freq_hz` secara konsisten.

### Mengapa melakukan pemeriksaan sebelum merekam?

Setelah instalasi mengikuti README, jalankan satu per satu:

```bash
python case_b.py doctor
python case_b.py selftest
python case_b.py demo --seed 7
```

| Perintah | Apa yang dilakukan program? | Apa yang harus diperiksa? |
| --- | --- | --- |
| `doctor` | Mencari HackRF Tools, mencatat versi paket, dan meminta informasi perangkat melalui `hackrf_info` jika tersedia. Tidak merekam sampel. | Untuk capture, perangkat harus terdeteksi. Jika belum terhubung, `unavailable` memang wajar dan analisis offline tetap dapat diuji. |
| `selftest` | Menjalankan uji DSP dan validasi pada data rekayasa kecil, termasuk CFO, gap, clipping, serta split sesi/orang. Tidak memakai radio. | `tests.txt` harus berakhir `OK`; jika gagal, tangani software dahulu. |
| `demo --seed 7` | Membuat raw/CSI sintetis, menjalankan ekstraksi serta evaluasi, dan menghasilkan contoh grafik. Seed membuat data uji dapat diulang. | Run harus selesai, hasil bertanda sintetis, dan grafik dapat dibuka. Jangan gunakan MAE demo sebagai hasil penelitian. |

**Siap masuk pilot jika:** software dapat dijalankan, HackRF terdeteksi untuk capture, kanal/posisi tercatat, ruang disk cukup, dan jadwal serta persetujuan subjek tersedia. Belum perlu mengambil data manusia untuk sekadar menjalankan `selftest` atau `demo`.

## 3. Menyiapkan jadwal dan pencatatan

**Tujuan:** setiap rekaman harus dapat dijawab “siapa subjeknya, sesi kapan, skenario apa, dan parameter apa yang digunakan?”. Tanpa pencatatan ini, evaluasi bisa mencampur kondisi berbeda atau memasukkan satu sesi ke latih dan uji sekaligus.

```bash
python case_b.py plan
mkdir -p data/metadata
cp config/metadata.example.json data/metadata/pilot.json
```

`plan` membuat rancangan jadwal dan template log di folder run, bukan memulai eksperimen. `mkdir -p` menyiapkan tempat metadata kerja; `cp` membuat salinan template agar contoh asli tetap tersedia. Edit salinannya sesuai rekaman yang akan diambil.

Folder run `plan` berisi `jadwal_protokol.csv`, header `log_sesi.csv`, dan template metadata. Salin jadwal ke `data/` untuk diisi selama eksperimen. Setiap trial harus mempunyai metadata terpisah.

| Skenario | Jumlah dan durasi | Keterangan |
| --- | --- | --- |
| Utama | 3 subjek × 3 target BPM × 3 sesi × 60 s = 27 trial | S1, S2, S3 diambil terpisah; P1, P2, P3 anonim |
| Ruang kosong | 3 ×60 s | Satu baseline setiap sesi, geometri tetap |
| Menahan napas | 1 × hingga 15 s per subjek | Opsional berdasarkan kesediaan; tidak dipaksakan |
| Orientasi | Usulan 2 orientasi ×3 pengulangan pada satu BPM | Catat sesi eksplorasi terpisah; `scenario=breathing`, isi `orientation` |

Urutan BPM bisa diacak atau diseimbangkan sebelum pengambilan. Simpan urutan sebenarnya dan seed bila diacak. Jangan mencampurkan trial eksplorasi dengan hasil utama tanpa membedakan analisisnya.

Metadata minimum: `session_id`, `subject_id`, `scenario`, `duration_s`. Untuk eksperimen yang dapat ditafsirkan, lengkapi semua kolom di template. Nilai `actual_breath_count` awalnya `null` karena hitungan aktual baru diketahui setelah capture. `target_bpm` bukan ground truth otomatis.

**Selesai jika:** jadwal berisi urutan trial yang akan dilakukan dan setiap trial punya metadata sendiri. Simpan denah/ukuran di catatan eksperimen; skrip tidak mengukur posisi perangkat secara otomatis.

## 4. Pilot dan pemisahan pemancar

**Tujuan:** menguji kelayakan penerimaan pada ruangan dan perangkat sebenarnya. Pilot mencari bukti adanya preamble Wi-Fi yang bisa diekstrak, bukan menguji akurasi napas dari rekaman 1 detik.

Edit `data/metadata/pilot.json`: `scenario="pilot"`, `subject_id="none"`, `target_bpm=null`, `actual_breath_count=null`, dan `duration_s=1`.

```bash
python case_b.py record --duration 1 --metadata data/metadata/pilot.json
```

`--duration 1` meminta satu detik sampel dari HackRF; `--metadata` memberi identitas/kondisi rekaman. Sesudah capture, skrip otomatis mendeteksi burst dan mengekstrak CSI. Metadata dan argumen durasi harus sama agar hitungan paket per detik tidak keliru.

Periksa `hackrf.log`, `qc.json`, dan `bursts.csv`. Pilot lulus jika:

- ≥20 paket valid dengan korelasi dua simbol L-LTF `rho > 0.6`.
- Laju paket ≥5 paket/s dan gap, termasuk tepi rekaman, ≤0,5 s.
- Fraksi komponen I/Q yang menyentuh batas ≤0,001 (0,1%, **ambang implementasi usulan**). Nilai ≥127 atau ≤−127 ditandai; periksa juga histogram/sebaran ADC bila perlu.

`adc_histogram.csv` menyimpan distribusi semua komponen I/Q pada −128..127. QC juga melaporkan sebaran CFO dan fraksi waktu dalam burst yang terdeteksi; occupancy ini bergantung threshold/minimal durasi burst dan bukan ukuran okupansi kanal terkalibrasi.

Beacon sekitar 10 paket/s tidak bisa memenuhi 20 paket dalam 1 detik. Gunakan trafik OFDM terkendali dari perangkat sendiri, atau lakukan pilot lebih panjang, misalnya 3 detik dengan metadata dan `--duration` sama-sama 3. Jangan mengubah hitungan paket agar terlihat lolos.

Skrip memakai detektor energi 1 µs, ambang 10 dB di atas kuantil daya 20% setiap chunk, penggabungan gap ≤2 µs, dan burst ≥24 µs. Ini heuristik untuk trafik yang relatif jarang. Pada kanal sangat padat, noise floor dapat terestimasi terlalu tinggi, beberapa paket bisa tergabung, dan CSI hilang. Perbaiki kanal atau parameter, lalu uji ulang sebelum sesi utama.

**Pemisahan pemancar wajib dibuktikan di lapangan.** HackRF menerima AP, klien, ACK, dan pemancar tetangga pada kanal yang sama. Interval beacon, daya, bentuk amplitudo, dan CFO dapat membantu inspeksi, tetapi CFO sendiri bukan identitas.

1. Uji router milik kelompok pada kanal sepi; bandingkan kondisi router hidup/mati dan trafik yang dikendalikan. Catat hasil dan kemungkinan frame dari klien.
2. Bila rentang CFO/RSSI membantu menyaring kelompok paket, tetapkan `cfo_range_hz` dan `rssi_range_dbfs` pada salinan config berdasarkan pilot, lalu pertahankan untuk data uji. Nilai `null` berarti tanpa penyaringan tersebut.
3. Jika belum dapat memisahkan, biarkan `tx_verified=false`. Skrip akan menyimpan CSI/QC, tetapi tidak menyatakan prediksi andal. Bila kanal padat tidak dapat dikendalikan, diperlukan receiver yang memvalidasi header/MAC atau alat CSI yang lebih lengkap; fitur tersebut belum diimplementasikan di sini.
4. Isi `tx_verified=true` hanya jika ada bukti yang layak, dan jelaskan bukti di `tx_verification_note`. Pernyataan operator ini tidak menjamin identifikasi MAC.

Di 2,4 GHz, frame DSSS/CCK 802.11b tidak punya L-LTF. Gunakan hanya setelah pilot membuktikan frame OFDM dapat diekstrak; 5 GHz adalah jalur utama rancangan ini.

Exit code `record`/`extract`: 0 selesai dan QC lulus, 2 QC tidak memenuhi batas, 1 error, 130 dihentikan operator. Artefak run dengan QC gagal tetap disimpan. QC penerimaan pilot terpisah dari verifikasi pemancar untuk analisis.

**Keputusan setelah pilot:** lanjutkan trial utama setelah kualitas penerimaan memadai dan asal pemancar sudah divalidasi. Jika belum, gunakan artefak gagal untuk diagnosis, ubah pengaturan yang relevan, catat perubahan, dan ulang pilot. Jangan mengambil 27 trial dahulu dengan harapan filter akan memperbaiki sinyal yang tidak layak.

## 5. Mengambil satu trial 60 detik

**Tujuan:** memperoleh satu rekaman terkontrol yang memuat cukup banyak siklus napas untuk FFT 30 detik, sekaligus memperoleh hitungan aktual dari pengamat. Satu trial berarti satu kondisi subjek/laju/orientasi yang terdokumentasi.

```bash
cp config/metadata.example.json data/metadata/B_S1_P1_10.json
```

Salinan ini adalah rencana capture untuk trial S1–P1–10 BPM. Nama file membantu pengelolaan, tetapi identitas yang dipakai analisis tetap berasal dari isi metadata.

Isi `trial_id="B_S1_P1_10"`, S1, P1, `scenario="breathing"`, target 10 BPM, durasi 60 s, denah/posisi, orientasi, kondisi ruangan, dan bukti pemancar. Terapkan konfigurasi yang sudah dikunci.

1. Beri waktu adaptasi. Subjek duduk nyaman dan diam; hindari berbicara, menoleh, atau menggaruk selama pengambilan.
2. Gunakan metronom 10 BPM: **satu ketukan per siklus penuh inspirasi–ekspirasi**, bukan per setengah siklus. Untuk 15 dan 20 BPM, ubah target secara konsisten.
3. Pengamat menghitung siklus napas aktual selama interval capture. Catat waktu mulai dan akhir; `capture_timing.json` berisi waktu perintah host, bukan timestamp ADC yang presisi.
4. Jalankan capture:

```bash
python case_b.py record --duration 60 --metadata data/metadata/B_S1_P1_10.json
```

Perintah di atas membuat satu raw sekitar 2,4 GB, lalu menghasilkan `csi.csv` dan QC pada folder run yang sama. Simpan path `OUTPUT: ...` yang dicetak; path inilah yang digunakan untuk analisis trial tersebut, bukan folder arsip pengujian software awal.

5. Perintah menunggu capture selesai, memeriksa ukuran byte, lalu mengekstrak CSI otomatis. Pembacaan raw dilakukan per chunk; file 2,4 GB tidak dimuat sekaligus ke array RAM.
6. Catat kejadian gerak dengan waktu relatif ke awal capture pada [data/anotasi_gerak.example.csv](data/anotasi_gerak.example.csv). Anotasi ini untuk audit/manual review, belum otomatis menghapus jendela. Jangan membuang trial gagal tanpa alasan tertulis.
7. Salin **metadata hasil run**, bukan template awal, ke metadata final. Contoh berikut menggunakan path run yang baru dicetak:

```bash
RUN="output/NAMA_RUN_RECORD"
cp "$RUN/metadata.json" data/metadata/B_S1_P1_10.final.json
```

Variabel `RUN` hanya mempersingkat penulisan path folder hasil capture. Penyalinan metadata hasil run membawa informasi QC dan konfigurasi yang benar ke file final; menyalin ulang template awal pada tahap ini justru menghilangkan informasi tersebut.

8. Edit file `.final.json`: isi `actual_breath_count`, kejadian gerak, catatan operator, dan kondisi ruangan. Pertahankan blok `qc` serta `radio_config` hasil ekstraksi. Contoh: 14 napas dalam 60 s menghasilkan GT 14 BPM walaupun target 15 BPM. Simpan juga bukti hitungan pada log sesi. Untuk menghindari perubahan artefak, jangan mengedit metadata asli di folder run.
9. Ulangi untuk ruang kosong, seluruh subjek/laju/sesi, dan kontrol. Buat folder run baru untuk setiap pengulangan. Raw tidak pernah dihapus otomatis.

Untuk rekaman lama:

```bash
python case_b.py extract /path/B_S1_P1_10.cs8 --metadata data/metadata/B_S1_P1_10.json
```

`extract` membaca file raw dari disk, bukan mengakses HackRF. Gunakan jika raw sudah tersedia atau ingin mengulang ekstraksi dengan konfigurasi yang tercatat. Perintah ini tidak menebak subjek/ground truth dari isi gelombang; metadata tetap harus benar.

Metadata durasi harus sesuai ukuran byte aktual. Capture parsial harus ditandai sebagai gagal dan dicatat; jangan memalsukan durasi agar lolos.

**Selesai jika:** raw/CSI dan QC tersedia, catatan gerak tersimpan, dan metadata final berisi hitungan aktual beserta kondisi rekaman. Trial gagal juga disimpan dengan alasan dan boleh diulang sebagai trial baru.

## 6. Apa yang dilakukan ekstraktor CSI

**Tujuan:** mengubah sampel radio kompleks yang belum bisa dibaca sebagai napas menjadi ukuran kanal pada 52 subcarrier untuk setiap paket. Anda tidak perlu menjalankan enam tahap berikut sebagai perintah terpisah; semuanya dikerjakan di dalam `record` atau `extract`.

1. Baca interleaved signed int8 I,Q; ubah menjadi kompleks dan bagi 128.
2. Deteksi burst dengan energi, simpan semua kandidat dan alasan penerimaan/penolakan di `bursts.csv`.
3. Estimasi coarse CFO dari pengulangan L-STF 16 sampel. Rentang tak ambigu sekitar ±625 kHz pada 20 Msps; burst yang rusak tidak selalu dapat dipulihkan.
4. Cari dua puncak korelasi L-LTF berjarak 64 sampel di sekitar posisi teoretis sampel 192 setelah awal burst. `rho` adalah minimum kedua korelasi setelah coarse correction. Perlu pula konsistensi pengulangan dua simbol ≥0,7.
5. Estimasi CFO residual dari beda fase dua LTF, koreksi rotasi, FFT masing-masing, lalu rata-ratakan. Hitung `H[k]=Y[k]/X[k]` untuk k=−26..−1 dan 1..26. Fine CFO sendiri hanya tak ambigu sekitar ±156,25 kHz.
6. Simpan `t_s,rssi_dbfs,cfo_hz,rho,amp_k-26,...,amp_k-1,amp_k1,...,amp_k26,label,session_id,subject_id`.

`rssi_dbfs` adalah daya rata-rata L-LTF pada sampel yang dinormalisasi; nilainya relatif, bukan dBm terkalibrasi. Fase tidak dianalisis. Ekstraktor tidak mendekode L-SIG/MAC atau memvalidasi CRC frame; `valid_packets` berarti kandidat preamble yang lolos kriteria CSI, bukan validasi paket penuh.

Timestamp adalah indeks sampel dibagi `fs`. Kehilangan sampel USB tidak dapat direkonstruksi dari `.cs8`; periksa log transfer, clock, dan durasi. Ukuran file yang benar sendiri tidak membuktikan tak ada sampel hilang. Satu berkas dibatasi <2^32 sampel agar kompatibel dengan batas hitungan `hackrf_transfer` yang umum.

**Yang diperiksa operator:** `csi.csv` memiliki 52 kolom amplitudo, `bursts.csv` menjelaskan paket yang ditolak, dan `qc.json` menunjukkan kualitas penerimaan. CSV yang berhasil dibuat saja belum membuktikan sinyal napas dapat terukur.

## 7. Pra-pemrosesan dan estimasi satu trial

**Tujuan:** mengubah deret amplitudo yang tidak beraturan menjadi sinyal waktu yang dapat dianalisis, lalu mencari frekuensi periodik yang sesuai pita napas. Tahap ini juga menunjukkan kapan hasil tidak layak ditafsirkan.

```bash
python case_b.py analyze "$RUN/csi.csv" --metadata data/metadata/B_S1_P1_10.final.json
```

Masukan pertama adalah CSI hasil trial yang sama; metadata final menyediakan kondisi serta GT aktual. Perintah ini bekerja offline tanpa HackRF. Buka `amplitude.png` untuk melihat perubahan terhadap waktu, `spectrum.png` untuk melihat frekuensi dominan, dan `predictions.csv` untuk membaca BPM serta alasan penolakan.

`analyze` default memakai k=1 sebagai baseline tetap. Jangan memilih carrier dengan melihat GT trial uji. Untuk carrier hasil latih, salin satu objek fold dari `folds.json` menjadi file model JSON yang mempunyai `selected_k`, lalu berikan `--model data/model_fold.json`; pastikan trial yang dianalisis adalah kelompok yang ditahan pada fold itu.

Alur analisis:

- Urutkan timestamp, hapus timestamp duplikat, dan terapkan ambang rho serta rentang CFO/RSSI yang telah dikunci.
- Hampel lokal 7 paket, ambang 3×1,4826 MAD. Ukuran dalam **paket**, sehingga rentang waktunya bergantung laju paket.
- Resample pada 10 Hz. Hold nilai di tepi hanya diterima bila gap tepi ≤0,5 s; durasinya dicatat pada QC.
- Mask gap >0,5 s, lalu detrend dan filter tiap bagian kontinu secara terpisah. Filter tidak melintasi gap. Segmen <5 s dimask karena dukungan temporal terlalu singkat.
- Butterworth orde 3, pita 0,08–0,55 Hz, SOS forward-backward (`sosfiltfilt`). Ini analisis offline dan menggunakan sampel masa depan dalam trial yang sama. Efek orde efektif dan redaman berubah karena filter dua arah; transient di tepi tetap mungkin terjadi.
- FFT **tanpa zero-padding**, Hann, 30 s, hop 15 s. Trial lengkap menghasilkan 0–30, 15–45, 30–60 s. Cari puncak 0,1–0,5 Hz, lalu BPM=60f. Resolusi grid 2 BPM; misalnya 15 BPM dapat terkuantisasi ke 14 atau 16 BPM.
- Confidence adalah daya bin puncak dibagi total daya pita. Ambang awal 0,35 dibakukan sebelum uji, bukan dipelajari dari data uji. Normalisasi spektral ini invarian skala; tidak ada scaler lintas trial yang di-fit pada seluruh dataset.
- Prediksi dinyatakan andal jika QC trial lolos, verifikasi pemancar tersedia, QC clipping berstatus `pass`, tidak ada gap panjang pada jendela, laju paket jendela ≥5/s, dan confidence lolos. Tanpa QC clipping dari ekstraktor, status `unknown` tidak dianggap lolos.

Semua kandidat puncak tetap ada di `peak_bpm`, sementara `pred_bpm` kosong bila tidak andal atau merupakan kontrol. Confidence bukan probabilitas klinis dan puncak kuat tetap bisa berasal dari gangguan periodik. Gerak badan tidak otomatis dideteksi; interpretasikan bersama anotasi.

Kontrol 15 s tidak dipaksa menjadi jendela 30 s. `control_energy.json` melaporkan mean-square sinyal terfilter relatif untuk diagnosis awal, dengan catatan transient. Tidak ada klasifikasi apnea atau deteksi ada/tidak ada napas. Kontrol kosong juga dapat memiliki puncak spektral dari lingkungan.

**Selesai jika:** hasil satu trial dapat ditelusuri dari QC sampai grafik dan prediksi. Jika `pred_bpm` kosong, periksa `reason` dan QC; jangan mengisi angka secara manual agar evaluasi terlihat lengkap.

## 8. Menyusun dataset dan evaluasi yang bebas kebocoran sesi

**Tujuan:** mengukur galat pada data yang dipisahkan dari proses memilih subcarrier. Analisis satu trial pada tahap sebelumnya hanya pemeriksaan awal; kesimpulan hipotesis dibuat dari evaluasi kumpulan trial ini.

Salin [data/dataset.example.csv](data/dataset.example.csv) menjadi `data/dataset.csv`, kemudian tambahkan seluruh trial yang nyata. Format:

```csv
trial_id,csi_path,metadata_path
B_S1_P1_10,../output/NAMA_RUN_S1/csi.csv,metadata/B_S1_P1_10.final.json
B_S2_P1_10,../output/NAMA_RUN_S2/csi.csv,metadata/B_S2_P1_10.final.json
B_S3_P1_10,../output/NAMA_RUN_S3/csi.csv,metadata/B_S3_P1_10.final.json
```

Path relatif dihitung dari lokasi `dataset.csv`; path absolut juga boleh. Nama `trial_id` harus unik dan sederhana. CSI dengan hash identik yang dimasukkan dua kali ditolak; aturan ini tidak bisa mendeteksi semua duplikasi semantik. Jangan memecah satu capture menjadi identitas sesi baru. Semua trial dari satu sesi pengambilan fisik harus mempunyai `session_id` yang sama. ID subjek juga harus konsisten lintas sesi.

```bash
python case_b.py evaluate data/dataset.csv --split session
python case_b.py evaluate data/dataset.csv --split person
```

`--split session` menahan satu sesi sebagai data uji, memilih carrier dari sesi lain, lalu merotasi sesi yang ditahan. Ini menjawab apakah metode tetap bekerja pada sesi pengambilan lain. `--split person` melakukan hal yang sama berdasarkan subjek untuk mengecek kemampuan pada orang yang tidak masuk data latih. Kedua perintah hanya membaca dataset dari disk dan membuat hasil baru; keduanya tidak merekam radio.

Evaluasi utama memakai leave-one-session-out: S1 uji, S2+S3 latih, lalu rotasi. Evaluasi tambahan memakai leave-one-person-out. Minimal dua kelompok diperlukan oleh skrip, tetapi rancangan utama tetap tiga sesi dan tiga subjek.

Pada setiap fold, pemilihan subcarrier hanya memakai **sinyal sesi latih**: rata-rata rasio energi puncak terhadap energi pita. GT tidak digunakan untuk seleksi. Ranking disimpan lengkap di `folds.json`, bersama daftar trial latih/uji. Metode yang dibandingkan:

| Metode | Definisi |
| --- | --- |
| `csi_selected` | Carrier dengan skor latih tertinggi |
| `csi_fixed` | Carrier tetap k=1 |
| `csi_median` | Median spektrum ternormalisasi 5 carrier terbaik dari latih; mencegah pembatalan sinyal beda fase |
| `rssi` | RSSI dari paket dan pipeline waktu yang sama |

Kontrol tidak digunakan memilih carrier dan tidak dimasukkan dalam MAE napas. Dataset sintetis dan nyata tidak boleh dicampurkan dalam satu evaluasi. Pipeline memakai konfigurasi tetap; jika ingin tuning ambang/filter, gunakan hanya kelompok latih atau nested validation dan simpan keputusan sebelum membuka sesi uji.

Ground truth dihitung sebagai `actual_breath_count ×60/duration_s`. Jika nilainya kosong, prediksi tetap dapat dibuat tetapi trial tidak masuk metrik galat. Jangan mengganti nilai kosong dengan target metronom. Hitungan 60 s adalah GT rata-rata trial, bukan GT independen tiap jendela 30 s; sebutkan keterbatasannya. Untuk variasi dalam trial, diperlukan anotasi tiap napas dan dukungan GT per jendela di pengembangan lanjutan.

**Selesai jika:** semua path dataset benar, identitas sesi/subjek konsisten, dan `folds.json` memperlihatkan pemisahan latih/uji yang sesuai pengambilan fisik. Periksa jumlah trial ber-GT dan pasangan prediksi sebelum membaca MAE.

## 9. Membaca keluaran evaluasi

**Tujuan:** menjawab pertanyaan riset dengan angka dan bukti kualitas data, bukan hanya memilih satu grafik yang terlihat baik. Mulai dari `quality.csv`, kemudian `coverage.csv`, lalu `metrics_paired.csv` dan grafik evaluasi.

| Berkas | Cara menggunakan |
| --- | --- |
| `predictions.csv` | Semua metode/jendela, GT aktual, kandidat puncak, confidence, status dan alasan |
| `metrics_paired.csv` | MAE, bias, selisih MAE; keseluruhan dan per target, subjek, sesi/fold, orientasi |
| `paired_windows.csv` | Hanya pasangan jendela CSI–RSSI yang sama-sama andal dan mempunyai GT |
| `coverage.csv` | Fraksi prediksi andal tiap metode serta MAE pada jendela valid metode itu sendiri |
| `quality.csv` | Jumlah/laju paket, gap, masking, clipping, verifikasi pemancar |
| `controls.csv` | Energi relatif kontrol pada carrier tetap dan RSSI; kontrol singkat belum punya FFT 30 s |
| `folds.json` | Audit pembagian data dan carrier yang dipilih hanya dari latih |
| `summary.json` | Ringkasan evaluasi dan penanda data sintetis |
| `evaluation.png` | Scatter GT–prediksi dan MAE CSI–RSSI pada jendela berpasangan |
| `plots/<trial>/` | Amplitudo dan contoh FFT per trial; status QC dicantumkan |

MAE adalah rata-rata `abs(pred−GT)`, bias adalah rata-rata `pred−GT`. Selisih MAE negatif berarti CSI lebih rendah pada pasangan yang tersedia. MAE rendah dengan coverage sangat kecil tidak membuktikan alat akurat secara umum. Laporkan juga trial gagal, jumlah pasangan, laju paket, gap, dan proporsi prediksi ditolak. Jendela overlap bukan sampel independen; jangan memakai 81 jendela sebagai 81 eksperimen manusia independen. Untuk interval ketidakpastian lanjutan, resample pada tingkat sesi/subjek, bukan tiap jendela.

Pengujian statistik dan klaim keberhasilan harus memakai data nyata yang mencakup tiga laju, seluruh sesi, dan jumlah subjek yang direncanakan. Skrip tidak otomatis menyatakan hipotesis berhasil ketika data belum lengkap.

**Tindakan untuk laporan:** tulis MAE/bias CSI dan RSSI pada pasangan yang sama, jumlah pasangan yang dinilai, coverage masing-masing metode, kondisi kegagalan, serta hasil kontrol. Jika CSI gagal mengungguli RSSI atau target ≤3 BPM tidak tercapai, laporkan hasil tersebut dan hubungkan dengan QC/gerak/geometri yang tercatat.

## 10. Dokumentasi setiap run dan reproduksi

**Tujuan:** memungkinkan anggota kelompok atau penguji menelusuri angka pada laporan ke data, konfigurasi, dan versi kode yang menghasilkannya.

Semua invocation `case_b.py`, termasuk `--help` dan argumen salah, membuat folder baru di `output/` selama folder tersebut dapat ditulis dan interpreter/dependensi dapat dimuat. Kegagalan OS sebelum program mulai, disk penuh, atau proses dimatikan paksa dapat meninggalkan status `running`; jangan menganggapnya selesai.

`manifest.json` memuat command, argumen, cwd, waktu UTC, status, versi paket, SHA256 input/kode, dan artefak. `source/` menyimpan snapshot implementasi. `config.json` adalah konfigurasi efektif; file di `source/config/` adalah snapshot berkas config repo. `command.txt` bisa digunakan untuk reproduksi dengan input yang sama. Pembacaan SHA256 raw 2,4 GB menambah waktu I/O tetapi tidak menggandakan raw.

Untuk mengunci lingkungan setelah instalasi yang berhasil:

```bash
python -m pip freeze > data/requirements_eksperimen.txt
```

`pip freeze` mencatat versi paket yang terpasang; tanda `>` menyimpan daftar tersebut ke file. Perintah ini tidak memasang paket dan tidak merekam radio. Simpan bersama identitas run yang dipakai dalam laporan.

Simpan file tersebut bersama laporan. Jangan memindahkan atau menghapus raw/metadata tanpa memperbarui salinan manifest dataset yang akan dipakai pada run baru. Folder lama tetap menjadi rekam jejak; hindari menimpa hasilnya. Simpan minimal satu `.cs8` nyata per skenario/kelas sesuai arahan dosen, dan arsipkan raw lain bila ruang memungkinkan.

## 11. Troubleshooting

**Tujuan:** memperbaiki tahap pertama yang gagal sebelum menjalankan tahap setelahnya. Gunakan pesan error dan QC dari run yang bersangkutan; mengulang evaluasi tidak akan memperbaiki capture yang tidak menghasilkan CSI.

| Gejala | Tindakan |
| --- | --- |
| `No HackRF boards found` | Periksa USB/driver/izin perangkat/USB forwarding WSL; jalankan `doctor` ulang |
| Tidak ada burst | Periksa antena, kanal, sample rate dan daya; kuantil noise floor dapat salah pada kanal padat |
| Burst banyak, CSI nol | Periksa OFDM vs 802.11b, primary channel, CFO, gain dan kualitas preamble |
| Clipping tinggi | Kurangi gain, jalankan pilot lagi, lalu kunci gain untuk semua pembanding |
| <5 paket/s atau gap panjang | Bangkitkan trafik terkendali, perbaiki posisi/kanal; jangan mengandalkan interpolasi untuk mengganti informasi |
| `pred_bpm` kosong | Lihat `reason`, `qc.json`, `tx_verified`, clipping, gap dan confidence |
| `Tidak ada jendela latih berkualitas` | Perbaiki data/QC sesi latih; jangan memilih carrier dari data uji agar evaluasi berjalan |
| MAE kosong | Periksa actual count, jumlah pasangan CSI–RSSI andal, dan metadata final |
| FFT 15 s kontrol kosong | Memang diharapkan; baca energi relatif dan keterbatasan kontrol singkat |
| Paket pemancar lain tercampur | Uji kanal/AP terkendali atau gunakan receiver yang memvalidasi identitas; jangan menganggap CFO identitas |

## 12. Checklist penyelesaian tiga minggu

**Tujuan:** memastikan proyek selesai sebagai studi kasus yang dapat dipertanggungjawabkan, termasuk proposal, data nyata, evaluasi, laporan, dan demo; keberhasilan menjalankan kode baru salah satu bagiannya.

**Minggu 1:** verifikasi ≥20 CSI valid dan laju paket; dokumentasikan denah dan pilot; bekukan protokol; siapkan proposal 1–2 halaman, hipotesis, eksplorasi, pembagian tugas, dan respons dua kritik/satu saran antarkelompok.

**Minggu 2:** ambil seluruh trial dan kontrol, simpan hitungan aktual serta anotasi gerak; ekstrak segera; tunjukkan raw contoh, QC dan FFT pada checkpoint; jalankan LOSO/LOPO serta eksplorasi carrier tetap vs terpilih atau orientasi.

**Minggu 3:** susun laporan maksimal 10 halaman: metode, dataset, split, MAE/bias/coverage, pembanding RSSI, kontrol, hasil negatif, keterbatasan ADC 8-bit/satu antena, dan saran. Siapkan presentasi 15 menit, demo 5 menit, dan tanya jawab silang 10 menit.

Luaran akhir: kode+requirements+README, metadata/log/jadwal, dataset CSI, raw contoh per skenario, grafik amplitudo/FFT/scatter/MAE, proposal, laporan, dan slide. File laporan dan slide belum dibuat oleh pipeline; isi dengan hasil pengukuran nyata setelah pengambilan selesai.

## Referensi teknis

- [Rancangan implementasi kelompok](https://docs.google.com/document/d/1Dq9eeTyFWjOBS815AwdrJpM95OYRrlaCPmg5FooycJE/edit).
- `case_base_csi_sdr.pdf`: bagian 3.3 memberikan urutan L-LTF dan estimator CSI yang menjadi dasar implementasi.
- [SciPy: butter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html) dan [sosfiltfilt](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.sosfiltfilt.html): filter SOS dan pemrosesan dua arah offline.
- [Great Scott Gadgets: hackrf_transfer source](https://github.com/greatscottgadgets/hackrf/blob/main/host/hackrf-tools/src/hackrf_transfer.c): parameter capture; opsi CLI juga diperiksa melalui `hackrf_transfer -h` lokal.
