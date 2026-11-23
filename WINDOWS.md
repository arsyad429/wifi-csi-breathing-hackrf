# Menjalankan di Windows PowerShell

Pipeline Python disiapkan untuk Windows, Linux, dan macOS. Halaman ini memberikan perintah **Windows native** dari instalasi sampai evaluasi; WSL tidak diperlukan. Pengujian yang telah dilakukan di workspace ini berlangsung di Linux. Validasi pada Windows asli dan capture dengan driver Windows tetap perlu dilakukan pada laptop pengguna; `selftest` disediakan untuk memeriksanya.

## 1. Lokasi proyek dan Python

Gunakan Windows 10/11 64-bit dengan Python 3.10+ 64-bit dari [python.org](https://www.python.org/downloads/windows/). Buka PowerShell dan periksa:

```powershell
py -3 --version
```

Ekstrak proyek ke lokasi pendek, misalnya `C:\wifi-csi`. Nama folder dengan spasi didukung, tetapi lokasi yang sangat panjang dapat melampaui batas path Windows saat hasil berada dalam subfolder. Jika diperlukan, letakkan hasil di `C:\csi-output` dengan `--output-root`. Jangan menyalin `.venv` dari Linux/macOS; buat ulang di Windows.

```powershell
Set-Location "C:\wifi-csi"
```

## 2. Penyiapan otomatis atau manual

Opsi otomatis, tanpa mengubah execution policy komputer secara permanen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -RunDemo
```

Skrip membuat `.venv`, memasang requirements, lalu menjalankan `doctor`, `selftest`, dan demo. Setup memiliki log sendiri di `output/<run>_setup_windows_.../setup.log`; perintah Python juga mempunyai folder run masing-masing. Setup tidak memasang driver, mengubah firmware, atau merekam radio. Laporan `device=unavailable` pada doctor berarti demo offline tetap bisa dijalankan, tetapi capture belum siap. Jika organisasi memblokir skrip melalui kebijakan perangkat, gunakan langkah manual berikut.

Jika Python atau HackRF berada di lokasi khusus:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_windows.ps1 -Python "C:\Python313\python.exe" -HackrfBin "C:\radioconda\Library\bin" -RunDemo
```

`-HackrfBin` hanya mengatur PATH proses setup; pada terminal lain atur PATH kembali sesuai langkah 4.

Opsi manual:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
.\.venv\Scripts\python.exe .\case_b.py doctor
.\.venv\Scripts\python.exe .\case_b.py selftest
.\.venv\Scripts\python.exe .\case_b.py demo --seed 7
```

Interpreter `.venv` dipanggil langsung sehingga aktivasi PowerShell tidak wajib. Jika ingin memakai `python` sebagai singkatan, aktifkan environment:

```powershell
.\.venv\Scripts\Activate.ps1
python .\case_b.py --help
```

Jika aktivasi diblokir, gunakan kembali path lengkap `.\.venv\Scripts\python.exe`. Semua contoh selanjutnya memakai path lengkap tersebut.

## 3. Merencanakan eksperimen

```powershell
.\.venv\Scripts\python.exe .\case_b.py plan
New-Item -ItemType Directory -Force .\data\metadata | Out-Null
Copy-Item .\config\metadata.example.json .\data\metadata\pilot.json
notepad .\data\metadata\pilot.json
```

Isi metadata pilot: `scenario=pilot`, `subject_id=none`, target/count `null`, `duration_s=1`. Untuk pilot beacon saja yang perlu ≥20 paket, pakai 3 detik pada metadata dan perintah capture. Detail protokol tetap mengikuti [PANDUAN_IMPLEMENTASI.md](PANDUAN_IMPLEMENTASI.md).

## 4. HackRF Tools dan driver USB

Untuk capture, `hackrf_transfer.exe` dan `hackrf_info.exe` harus dapat dijalankan dari PowerShell, termasuk DLL dependensinya. Dokumentasi resmi HackRF saat ini menyediakan jalur binary melalui radioconda atau artefak build resmi. Ikuti tautan unduhan dari [Installing HackRF Software](https://hackrf.readthedocs.io/en/latest/installing_hackrf_software.html#windows-binaries); `pip install -r requirements.txt` memasang paket Python saja.

Jika direktori binary belum ada di PATH, tambahkan pada terminal aktif. **Ganti path contoh** dengan lokasi sebenarnya yang berisi `.exe` dan DLL:

```powershell
$env:PATH = "C:\radioconda\Library\bin;$env:PATH"
Get-Command hackrf_transfer.exe
Get-Command hackrf_info.exe
hackrf_info.exe
.\.venv\Scripts\python.exe .\case_b.py doctor
```

Bila memakai radioconda, terminal radioconda yang telah diaktifkan juga dapat menyediakan PATH dan DLL yang diperlukan. Python analisis tetap dapat memakai `.venv` proyek melalui path lengkap.

Pasang driver yang sesuai hanya bila HackRF belum dapat dibuka. Jalur umum adalah [Zadig](https://zadig.akeo.ie/): sambungkan HackRF, pilih **Options → List All Devices**, pilih perangkat **HackRF One** yang benar, lalu pasang **WinUSB**. Rujukan: [HackRF host README](https://github.com/greatscottgadgets/hackrf/blob/main/host/README.md) dan [libusb Windows](https://github.com/libusb/libusb/wiki/Windows). Jangan memilih perangkat USB lain pada daftar. Tutup SDR# atau aplikasi lain yang sedang memegang HackRF sebelum `doctor`/capture.

## 5. Capture dan ekstraksi

Pilot, setelah metadata disesuaikan dan perangkat terdeteksi:

```powershell
.\.venv\Scripts\python.exe .\case_b.py record --duration 1 --metadata .\data\metadata\pilot.json
```

Trial utama:

```powershell
Copy-Item .\config\metadata.example.json .\data\metadata\B_S1_P1_10.json
notepad .\data\metadata\B_S1_P1_10.json
.\.venv\Scripts\python.exe .\case_b.py record --duration 60 --metadata .\data\metadata\B_S1_P1_10.json
```

Untuk file raw yang sudah ada, termasuk path dengan spasi:

```powershell
.\.venv\Scripts\python.exe .\case_b.py extract "D:\Data CSI\B_S1_P1_10.cs8" --metadata .\data\metadata\B_S1_P1_10.json
```

Jika ingin output lebih pendek atau di disk lain:

```powershell
.\.venv\Scripts\python.exe .\case_b.py --output-root "D:\csi-output" record --duration 60 --metadata .\data\metadata\B_S1_P1_10.json
```

Satu raw 60 s sekitar 2,4 GB. Gunakan disk dengan kapasitas cukup dan filesystem yang mendukung file besar. File 60 s masih di bawah batas 4 GB FAT32, tetapi capture yang lebih lama dapat melampauinya.

## 6. Ground truth dan analisis

Ganti `NAMA_RUN_RECORD` dengan folder yang dicetak saat capture. Salin metadata hasil run agar blok QC ikut terbawa, lalu isi hitungan aktual dari pengamat:

```powershell
$run = ".\output\NAMA_RUN_RECORD"
Copy-Item "$run\metadata.json" .\data\metadata\B_S1_P1_10.final.json
notepad .\data\metadata\B_S1_P1_10.final.json
.\.venv\Scripts\python.exe .\case_b.py analyze "$run\csi.csv" --metadata .\data\metadata\B_S1_P1_10.final.json
```

JSON dibaca sebagai UTF-8 dengan/tanpa BOM, sehingga file UTF-8 yang disimpan melalui PowerShell 5.1 juga didukung. Jangan menyimpan metadata sebagai UTF-16. Menyunting dengan Notepad modern dan menyimpan UTF-8 adalah pilihan sederhana.

## 7. Evaluasi dan membuka hasil

```powershell
Copy-Item .\data\dataset.example.csv .\data\dataset.csv
notepad .\data\dataset.csv
.\.venv\Scripts\python.exe .\case_b.py evaluate .\data\dataset.csv --split session
.\.venv\Scripts\python.exe .\case_b.py evaluate .\data\dataset.csv --split person
Invoke-Item .\output
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding UTF8 .\data\requirements_eksperimen.txt
```

File dataset harus menunjuk CSV/metadata yang benar untuk semua trial. CSV mengizinkan slash `/` pada path Windows, misalnya `../output/NAMA_RUN/csi.csv`; untuk drive berbeda gunakan path absolut. Di JSON, backslash harus digandakan (`D:\\Data CSI\\file.cs8`) atau gunakan slash `/`. Pada argumen PowerShell, cukup kutip path: `"D:\Data CSI\file.cs8"`.

Di Windows, `command.txt` memakai sintaks PowerShell dengan operator `&`; `command_argv.json` menyimpan daftar argumen yang tidak bergantung shell. Di Linux/macOS, `command.txt` menggunakan sintaks shell POSIX.

## 8. Masalah umum

| Masalah | Pemeriksaan |
| --- | --- |
| `py` tidak dikenal | Pasang Python launcher atau gunakan path lengkap `python.exe` |
| Aktivasi script diblokir | Panggil `.venv\Scripts\python.exe` langsung |
| `hackrf_transfer` tidak ditemukan | Periksa PATH terminal aktif dengan `Get-Command` |
| DLL hilang | Pertahankan DLL dari paket binary yang sama; gunakan terminal radioconda aktif bila diperlukan |
| HackRF tidak terdeteksi | Periksa USB data, mode HackRF bila ada PortaPack, driver WinUSB, dan aplikasi lain |
| Error path terlalu panjang | Tempatkan proyek di `C:\wifi-csi` dan output di path pendek |
| JSON gagal dibaca | Simpan UTF-8, gunakan `null` untuk nilai kosong, jangan ada koma terakhir |
| Ingin menjalankan di WSL | Ikuti bagian Linux dan USB passthrough; jangan campur `.venv` Windows dan Linux |

Pengujian lintas OS disiapkan di `.github/workflows/test.yml` untuk dijalankan bila proyek dimasukkan ke GitHub. Workflow tidak merekam radio; perangkat dan driver perlu diuji lokal.
