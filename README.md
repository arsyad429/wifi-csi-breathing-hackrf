# Case B: Pemantauan Laju Napas dengan Wi-Fi CSI dan HackRF One

Implementasi offline **I/Q `.cs8` → burst → L-LTF → koreksi CFO → 52 CSI → estimasi BPM → evaluasi CSI dan RSSI**. HackRF hanya digunakan sebagai penerima. Seluruh perintah CLI menyimpan dokumentasi run di `output/`, termasuk run gagal.

Mulai dari [PANDUAN_IMPLEMENTASI.md](PANDUAN_IMPLEMENTASI.md) untuk prosedur eksperimen, ground truth, evaluasi, serta penyelesaian luaran kuliah. Rancangan bersumber dari [Google Docs kelompok](https://docs.google.com/document/d/1Dq9eeTyFWjOBS815AwdrJpM95OYRrlaCPmg5FooycJE/edit) dan [PDF arahan dosen](case_base_csi_sdr.pdf), terutama bagian 3 dan Case B.

**Pilih OS:** perintah Linux/macOS tersedia di bawah; langkah lengkap **Windows PowerShell**, termasuk driver HackRF, capture, dan evaluasi, tersedia di [WINDOWS.md](WINDOWS.md). Kode Python yang digunakan sama.

Untuk mengambil kode dari GitHub, jalankan pada terminal Windows, Linux, atau macOS:

```bash
git clone https://github.com/arsyad429/wifi-csi-breathing-hackrf.git
cd wifi-csi-breathing-hackrf
```

Repository publik memuat kode, panduan, konfigurasi/template, pengujian, dan PDF arahan kasus. `.venv/`, `output/`, raw `.cs8`, cache, dan file sementara dikecualikan melalui `.gitignore`; hasil demo dapat dibuat sendiri dengan perintah pada bagian 2.

## 1. Membuat virtual environment

Gunakan Python **3.10 atau lebih baru**. Perintah berikut dijalankan dari folder proyek ini, bukan dari repo referensi.

Ubuntu/Debian/WSL:

```bash
sudo apt update
sudo apt install python3-venv hackrf
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

macOS: pasang Python dan HackRF terlebih dahulu (`brew install python hackrf`), lalu jalankan empat baris mulai `python3 -m venv .venv` di atas.

Windows PowerShell, penyiapan manual:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Jika aktivasi PowerShell diblokir, jalankan `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` dan gunakan interpreter tersebut langsung. Untuk capture di Windows diperlukan driver dan `hackrf_transfer` yang berfungsi; di WSL perangkat USB harus diteruskan ke WSL. Referensi lokal: `../LoRa_SDR/SSH-WSL.md`.

Opsi setup Windows otomatis, termasuk selftest dan demo:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -RunDemo
```

Setiap terminal baru perlu aktivasi lagi. Periksa dengan `python -c "import sys; print(sys.executable)"`; hasilnya harus menunjuk `.venv`. Keluar dengan `deactivate`. Jangan memakai `sudo pip`. Versi paket aktual dicatat pada `manifest.json` setiap run; `requirements.txt` berisi rentang dependensi, bukan lock file.

Daftar versi lengkap yang telah diuji dalam `.venv` Linux/Python 3.13 disimpan di `data/requirements_teruji_linux_py313.txt`. Gunakan `requirements.txt` untuk instalasi awal lintas OS/Python; berkas versi teruji adalah rekam jejak lingkungan pengujian ini.

## 2. Coba tanpa perangkat radio

```bash
python case_b.py doctor
python case_b.py selftest
python case_b.py demo --seed 7
python case_b.py plan
```

Setiap perintah mencetak `OUTPUT: ...` yang menunjukkan lokasi hasilnya. `demo` membuat pilot I/Q 1 detik, 33 trial CSI sintetis, dan evaluasi tiga fold. Ukurannya sekitar 70 MB dan membutuhkan puluhan detik, tergantung laptop. **Angka demo hanya verifikasi perangkat lunak, bukan bukti akurasi alat atau hasil studi manusia.** Gangguan RSSI sengaja dibuat dalam generator; perbandingan demo tidak membuktikan CSI lebih baik di dunia nyata.

## 3. Perintah untuk data nyata

**Linux/macOS (Bash/Zsh):**

```bash
# Salin dan lengkapi metadata sebelum capture.
mkdir -p data/metadata
cp config/metadata.example.json data/metadata/B_S1_P1_10.json

# Capture 60 s dan langsung ekstrak CSI; durasi harus sama dengan metadata.
python case_b.py record --duration 60 --metadata data/metadata/B_S1_P1_10.json

# Alternatif: rekaman .cs8 yang sudah tersedia.
python case_b.py extract /path/rekaman.cs8 --metadata data/metadata/B_S1_P1_10.json

# Ganti NAMA_RUN dengan folder yang dicetak perintah record/extract.
python case_b.py analyze output/NAMA_RUN/csi.csv --metadata output/NAMA_RUN/metadata.json

# Setelah metadata ground truth lengkap dan dataset.csv disusun:
python case_b.py evaluate data/dataset.csv --split session
python case_b.py evaluate data/dataset.csv --split person
```

**Windows (PowerShell, tanpa perlu aktivasi):**

```powershell
New-Item -ItemType Directory -Force .\data\metadata | Out-Null
Copy-Item .\config\metadata.example.json .\data\metadata\B_S1_P1_10.json
# Lengkapi metadata terlebih dahulu, sesuai panduan.
notepad .\data\metadata\B_S1_P1_10.json
.\.venv\Scripts\python.exe .\case_b.py record --duration 60 --metadata .\data\metadata\B_S1_P1_10.json
.\.venv\Scripts\python.exe .\case_b.py extract "D:\Data CSI\rekaman.cs8" --metadata .\data\metadata\B_S1_P1_10.json
# Ganti NAMA_RUN dengan folder hasil record/extract.
.\.venv\Scripts\python.exe .\case_b.py analyze .\output\NAMA_RUN\csi.csv --metadata .\output\NAMA_RUN\metadata.json
# Setelah metadata ground truth final dan dataset.csv lengkap:
.\.venv\Scripts\python.exe .\case_b.py evaluate .\data\dataset.csv --split session
.\.venv\Scripts\python.exe .\case_b.py evaluate .\data\dataset.csv --split person
```

Pada `analyze` tanpa model, subcarrier memakai baseline tetap `k=1`, sehingga tidak memilih carrier dari data uji. Seleksi otomatis dari sesi latih dilakukan oleh `evaluate`. Panduan menjelaskan cara mengisi hitungan napas setelah capture dan membawa hasil QC ke metadata final.

Konfigurasi bawaan ada di [config/default.json](config/default.json). Salin file ini untuk eksperimen lain, lalu gunakan:

```bash
python case_b.py --config config/eksperimen.json --output-root output evaluate data/dataset.csv
python case_b.py --help
```

Opsi `--config` dan `--output-root` juga boleh diletakkan setelah subcommand. Sample rate dikunci 20 Msps karena estimator ini menggunakan FFT 64 sampel dari legacy OFDM 20 MHz.

## 4. Fungsi tiap folder dan file proyek

Struktur proyek berikut membedakan kode, konfigurasi, data masukan, dan hasil pemrosesan. Folder bertanda “dibuat saat digunakan” mungkin belum ada sebelum perintah terkait dijalankan.

```text
proyek/
  README.md
  PANDUAN_IMPLEMENTASI.md
  WINDOWS.md
  case_base_csi_sdr.pdf
  case_b.py
  requirements.txt
  setup_windows.ps1
  .gitignore
  caseb/
    __init__.py
    radio.py
    analysis.py
    runlog.py
    synthetic.py
  config/
    default.json
    metadata.example.json
  data/
    dataset.example.csv
    anotasi_gerak.example.csv
    requirements_teruji_linux_py313.txt
    metadata/                 # dibuat saat digunakan
    dataset.csv               # dibuat saat menyiapkan data nyata
  tests/
    test_pipeline.py
  .github/workflows/
    test.yml
  output/
    README.md
    hasil pengujian perangkat lunak awal/
    <run_baru>/               # dibuat setiap menjalankan CLI
  .venv/                      # dibuat saat instalasi
  __pycache__/                # cache otomatis Python
  tmp/pdfs/                   # gambar sementara untuk membaca PDF arahan
```

### Folder

| Folder | Fungsi |
| --- | --- |
| `caseb/` | Modul Python yang menjalankan tahap-tahap pemrosesan sinyal dan dokumentasi run. Dipanggil oleh `case_b.py`. |
| `config/` | Parameter radio/pemrosesan dan contoh metadata; salin contoh sebelum menyesuaikan eksperimen. |
| `data/` | Template, metadata final, daftar trial untuk evaluasi, dan catatan lingkungan Python. Bukan lokasi hasil run otomatis. |
| `data/metadata/` | Metadata masing-masing trial yang diisi operator, termasuk hitungan napas aktual. Dibuat saat menyiapkan eksperimen. |
| `tests/` | Pengujian numerik dan pemeriksaan validasi yang bisa dijalankan tanpa HackRF. |
| `.github/workflows/` | Konfigurasi pengujian otomatis Windows, Linux, dan macOS jika proyek digunakan di GitHub. |
| `output/` | Hasil perintah: log, konfigurasi, tabel, grafik, dan raw jika perintah melakukan capture. Jenis datanya harus dilihat dari perintah dan metadata. |
| `output/hasil pengujian perangkat lunak awal/` | Arsip 15 run awal dari pembuatan perangkat lunak. Berisi data sintetis dan pemeriksaan software; **bukan hasil pengukuran HackRF**. |
| `.venv/` | Interpreter dan paket Python khusus proyek. Dibuat ulang pada setiap OS; tidak perlu diedit atau disalin antar-OS. |
| `__pycache__/` | Bytecode/cache yang dibuat otomatis oleh Python, termasuk pada subfolder modul dan tests. Bukan data eksperimen. |
| `tmp/pdfs/` | Gambar halaman PDF yang dibuat untuk memeriksa arahan kasus; bukan rekaman radio atau luaran eksperimen. |

### File utama, kode, konfigurasi, dan template

| File | Fungsi |
| --- | --- |
| `README.md` | Titik mulai: instalasi, pilihan perintah per OS, struktur proyek, dan penjelasan hasil. |
| `PANDUAN_IMPLEMENTASI.md` | Langkah penelitian lengkap: pilot, geometri, protokol trial, ground truth, evaluasi, dan checklist luaran. |
| `WINDOWS.md` | Langkah PowerShell, instalasi HackRF Tools/driver, PATH, capture, analisis, dan troubleshooting Windows. |
| `case_base_csi_sdr.pdf` | Arahan asli studi kasus dari pengampu; menjadi sumber ketentuan dan pipeline wajib. |
| `case_b.py` | CLI, validasi, capture, integrasi pipeline |
| `caseb/__init__.py` | Menandai `caseb` sebagai package Python agar modulnya dapat diimpor. |
| `caseb/radio.py` | Baca I/Q per chunk, burst, CFO, korelasi L-LTF, CSI dan QC |
| `caseb/analysis.py` | Hampel, resampling, masking gap, filter, FFT, seleksi carrier, LOSO/LOPO |
| `caseb/runlog.py` | Folder run unik, log, versi, SHA256 input, snapshot kode, status |
| `caseb/synthetic.py` | Data uji sintetis dengan label yang eksplisit |
| `config/default.json` | Frekuensi/kanal, gain, ambang ekstraksi/QC, filter, panjang jendela FFT, dan parameter evaluasi. |
| `config/metadata.example.json` | Contoh identitas sesi/subjek, skenario, durasi, target, hitungan aktual, posisi, dan bukti verifikasi pemancar. |
| `data/dataset.example.csv` | Contoh daftar trial yang menghubungkan `trial_id`, file CSI, dan metadata. Path contoh perlu diganti. |
| `data/anotasi_gerak.example.csv` | Contoh pencatatan waktu gerak selain napas; baris contoh bukan kejadian aktual. |
| `data/requirements_teruji_linux_py313.txt` | Daftar versi lengkap paket pada lingkungan Linux/Python 3.13 yang dipakai menguji implementasi awal. |
| `data/dataset.csv` | Daftar trial aktual yang disusun operator sebagai masukan `evaluate`; dibuat dari contoh setelah data tersedia. |
| `data/metadata/*.json` | File metadata per trial, termasuk versi final setelah hitungan napas pengamat dilengkapi. |
| `tests/test_pipeline.py` | Uji numerik dan perlindungan validasi |
| `requirements.txt` | Dependensi yang dipasang di `.venv` |
| `setup_windows.ps1` | Membuat `.venv` Windows, memasang dependensi, menjalankan doctor/selftest, dan menjalankan demo jika diminta. |
| `.github/workflows/test.yml` | Menjalankan selftest lintas OS/versi Python melalui GitHub Actions dan menyimpan log sebagai artefak CI. |
| `.gitignore` | Mengecualikan environment, cache, output, raw `.cs8`, dan file sementara dari pelacakan Git. |

## 5. Isi folder output

Seluruh hasil pengujian yang dibuat saat implementasi awal sudah dipisahkan ke `output/hasil pengujian perangkat lunak awal/`. Arsip lokal ini tidak diunggah ke GitHub. Arsip tersebut berisi demo, ekstraksi raw sintetis, selftest, doctor, template jadwal, help CLI, dan uji argumen gagal. **Belum ada rekaman radio atau napas manusia nyata di dalam arsip ini.**

`output/README.md` adalah penunjuk arsip dan penjelasan hasil berikutnya. `relokasi.json` di dalam arsip memetakan lokasi lama ke lokasi baru; manifest dan log historis tetap menyimpan informasi asli. Untuk mengulang perintah lama, sesuaikan path input dengan lokasi sekarang.

Run berikutnya tetap dibuat langsung di `output/<timestamp_UTC>_<command>_<id>/`; pemindahan arsip tidak mengubah perilaku skrip. Data di luar arsip juga bisa sintetis jika perintahnya `demo`.

```text
output/<timestamp_UTC>_<command>_<id>/
  README.md                  # status dan tautan artefak
  command.txt                # perintah yang dijalankan
  command_argv.json          # daftar argumen lintas OS
  manifest.json              # argumen, input SHA256, versi, status, daftar artefak
  config.json                # parameter efektif, kecuali perintah help
  run.log                    # log/error
  source/                    # snapshot kode, config, requirements pada waktu run
  ...                        # hasil sesuai jenis perintah
```

### Dokumentasi umum setiap run

| File/folder | Fungsi |
| --- | --- |
| `README.md` | Status run dan tautan menuju artefak yang dibuat. |
| `command.txt` | Perintah untuk reproduksi, memakai sintaks PowerShell di Windows atau shell POSIX di Linux/macOS. |
| `command_argv.json` | Argumen perintah dalam bentuk daftar, tanpa bergantung pada aturan pengutipan shell. |
| `manifest.json` | Waktu, status, argumen, versi paket, SHA256 input/kode, dan daftar artefak. |
| `config.json` | Parameter efektif saat run, berbeda dari template config yang bisa berubah kemudian. |
| `run.log` | Pesan proses, peringatan, dan rincian error. |
| `source/` | Salinan kode, config, tests, requirements, dan dokumentasi yang tersedia saat run; salinan ini adalah rekam jejak versi lama. |
| `error.txt` | Traceback jika perintah gagal; baca penyebab sebelum mengulang. |
| `cli_output.txt` | Keluaran bantuan CLI jika menjalankan `--help`. |

### Hasil capture dan ekstraksi

| File | Fungsi |
| --- | --- |
| `capture.cs8` | Raw interleaved int8 I/Q dari capture `record` yang berhasil; sumber untuk ekstraksi ulang. |
| `capture_command.json` | Daftar argumen `hackrf_transfer` yang dipakai merekam. |
| `capture_timing.json` | Waktu mulai perintah pada host; bukan timestamp ADC yang presisi. |
| `hackrf.log` | Keluaran native HackRF Tools untuk memeriksa transfer, kegagalan, atau gangguan perangkat. |
| `csi.csv` | Timestamp, RSSI relatif, CFO, korelasi L-LTF, 52 amplitudo CSI, dan identitas trial. Bisa berasal dari raw nyata atau sintetis; periksa asal input. |
| `bursts.csv` | Semua kandidat burst dan alasan diterima/ditolak sebagai CSI. |
| `adc_histogram.csv` | Distribusi nilai komponen ADC −128..127 untuk pemeriksaan clipping. |
| `qc.json` | Jumlah/laju paket, gap, clipping, sebaran CFO, dan status kualitas. Pada `analyze`, berisi QC deret waktu yang digunakan. |
| `metadata.json` | Metadata trial ditambah durasi aktual, QC, dan konfigurasi radio. |
| `log_sesi.csv` | Ringkasan kondisi sesi, subjek, target/count, radio, posisi, dan kualitas paket. |

### Hasil analisis dan evaluasi

| File/folder | Fungsi |
| --- | --- |
| `preprocessed.csv` | Grid waktu seragam, mask validitas, dan amplitudo/RSSI setelah detrend serta filter. |
| `model_used.json` | Carrier yang digunakan oleh analisis satu trial beserta sumber modelnya. |
| `predictions.csv` | Prediksi/kandidat BPM tiap metode dan jendela, confidence, GT bila tersedia, serta alasan jika tidak andal. |
| `amplitude.png` | Grafik amplitudo CSI terhadap waktu dan sinyal setelah filter. |
| `spectrum.png` | Spektrum FFT satu jendela beserta puncak CSI/RSSI; kontrol singkat diberi keterangan tanpa memaksakan FFT 30 s. |
| `control_energy.json` | Energi relatif sinyal terfilter untuk satu trial/kontrol; bukan keputusan apnea. |
| `metrics_paired.csv` | MAE, bias, dan selisih CSI–RSSI pada pasangan jendela yang sama-sama andal. |
| `paired_windows.csv` | Baris jendela yang digunakan untuk perbandingan berpasangan tersebut. |
| `coverage.csv` | Jumlah/fraksi prediksi andal tiap metode dan MAE pada jendela valid masing-masing metode. |
| `quality.csv` | Ringkasan QC seluruh trial dalam evaluasi. |
| `controls.csv` | Energi relatif pada trial ruang kosong dan tahan napas. |
| `folds.json` | Pembagian trial latih/uji serta ranking/pilihan carrier setiap fold, untuk audit kebocoran data. |
| `summary.json` | Ringkasan split, jumlah trial/fold, ketersediaan GT, dan metrik evaluasi. |
| `evaluation.png` | Scatter ground truth–prediksi dan perbandingan MAE CSI–RSSI. |
| `plots/<trial_id>/` | Grafik amplitudo dan spektrum yang dipisahkan per trial. |

### Hasil pemeriksaan, perencanaan, dan demo

| File/folder | Fungsi |
| --- | --- |
| `doctor.json`, `hackrf_info.txt` | Pemeriksaan dependensi, lokasi tools, dan deteksi perangkat. Tidak merekam sinyal. |
| `tests.txt` | Daftar pengujian otomatis dan status lolos/gagal. |
| `jadwal_protokol.csv` | Jadwal trial usulan yang dihasilkan `plan`, untuk disesuaikan operator. |
| `metadata.example.json` | Salinan template metadata dari perintah `plan`. |
| `SYNTHETIC.json` | Penanda data sintetis, seed, dan batas penggunaan hasil demo. |
| `synthetic_pilot.cs8` | I/Q buatan Python untuk memeriksa ekstraktor; **bukan hasil penerimaan HackRF**. |
| `iq_truth.json` | Kanal, CFO, dan waktu paket sintetis yang diketahui untuk pembanding numerik. |
| `iq_verification.json` | Galat amplitudo/CFO hasil ekstraksi dibanding nilai sintetis yang diketahui. |
| `synthetic_dataset/` | CSI dan metadata buatan untuk 33 trial; setiap subfolder mewakili satu trial sintetis. |
| `synthetic_dataset/dataset.csv` | Daftar trial sintetis yang dimasukkan ke evaluator. |
| `evaluation/` | Hasil evaluasi LOSO terhadap dataset sintetis saat menjalankan `demo`. |
| `short_control/` | Contoh analisis kontrol sintetis 15 s untuk memeriksa penanganan durasi pendek. |
| `setup.log` | Transkrip instalasi dan pemeriksaan jika menggunakan `setup_windows.ps1`. |
| `relokasi.json` | Khusus arsip pengujian awal: pemetaan folder run sebelum/sesudah pemindahan. |

Run baru selalu membuat folder baru. Data raw tidak dihapus otomatis. Arsipkan raw yang dipilih setelah memastikan CSI dan metadata benar. Snapshot kode bisa dijalankan kembali melalui `source/case_b.py`; pasang dependensi terlebih dahulu dan berikan input yang dirujuk manifest.

## 6. Batas penggunaan

Pemisahan pemancar berdasarkan rentang CFO/RSSI hanyalah penyaring kandidat. Skrip tidak mendekode MAC atau payload. `tx_verified=true` merupakan pernyataan operator berdasarkan uji pemancar terkendali, bukan hasil identifikasi otomatis. Tanpa verifikasi tersebut dan QC clipping yang lolos, angka spektral tetap tersimpan, tetapi prediksi tidak dinyatakan andal.

Pipeline ini adalah purwarupa praktikum, bukan alat kesehatan. Persetujuan subjek, protokol kontrol, batas interpretasi, dan checklist penyelesaian dijelaskan di panduan.
