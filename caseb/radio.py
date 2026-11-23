"""Streaming burst detection, L-STF coarse CFO, L-LTF fine CFO dan 52 CSI."""
import csv
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from .runlog import write_json

K = np.r_[np.arange(-26, 0), np.arange(1, 27)]
L = np.array([1,1,-1,-1,1,1,-1,1,-1,1,1,1,1,1,1,-1,-1,1,1,-1,1,-1,1,1,1,1,0,
              1,-1,-1,1,1,-1,1,-1,1,-1,-1,-1,-1,-1,1,1,-1,-1,1,-1,1,-1,1,1,1,1])
X = np.zeros(64, complex)
X[np.arange(-26, 27) % 64] = L
LTF = np.fft.ifft(X)
AMP = [f"amp_k{k}" for k in K]


def read_iq(raw, start, stop):
    v = raw[2*max(0, start):2*stop].astype(np.float32)
    return (v[::2] + 1j*v[1::2]) / 128.0


def burst_intervals(raw, cfg):
    """1 us energy bins; carry intervals across chunks, merge gaps <= 2 us."""
    n = len(raw) // 2
    step = 20
    chunk = max(step, int(cfg["chunk_samples"]) // step * step)
    pending = None
    minimum = int(cfg["min_burst_us"] * 20)
    for base in range(0, n, chunk):
        iq = read_iq(raw, base, min(base+chunk, n))
        used = len(iq) // step * step
        if not used:
            continue
        p = np.mean(np.abs(iq[:used].reshape(-1, step))**2, axis=1)
        # Quantile is a heuristic: dense occupancy needs a calibrated threshold.
        floor = max(float(np.quantile(p, 0.2)), 1e-8)
        active = p > floor * 10**(cfg["energy_threshold_db"] / 10)
        edges = np.diff(np.r_[False, active, False].astype(np.int8))
        for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            current = (base + int(a)*step, base + int(b)*step)
            if pending and current[0] - pending[1] <= 40:
                pending = (pending[0], current[1])
            else:
                if pending and pending[1] - pending[0] >= minimum:
                    yield pending
                pending = current
        if pending and base+used-pending[1] > 40:
            if pending[1]-pending[0] >= minimum:
                yield pending
            pending = None
    if pending and pending[1]-pending[0] >= minimum:
        yield pending


def estimate_ltf(seg, burst_offset, fs=20e6):
    """Coarse estimate from repeated STF; then require two LTF matches 64 apart."""
    a = max(0, burst_offset + 20)
    stf = seg[a:a+112]
    if len(stf) < 112 or len(seg) < 192:
        return None
    coarse = np.angle(np.vdot(stf[:-16], stf[16:])) / 16
    corrected = seg * np.exp(-1j * coarse * np.arange(len(seg)))
    energy = np.convolve(np.abs(corrected)**2, np.ones(64), "valid")
    rho = np.abs(np.correlate(corrected, LTF, "valid")) / (
        np.linalg.norm(LTF) * np.sqrt(energy) + 1e-12)
    paired = np.minimum(rho[:-64], rho[64:])
    # Search around the expected first LTF (burst onset + 192), allowing onset error.
    lo, hi = max(0, burst_offset+120), min(len(paired), burst_offset+260)
    if hi <= lo:
        return None
    i = lo + int(np.argmax(paired[lo:hi]))
    s1, s2 = corrected[i:i+64], corrected[i+64:i+128]
    repeat = abs(np.vdot(s1, s2)) / (np.linalg.norm(s1)*np.linalg.norm(s2)+1e-12)
    if repeat < 0.7:
        return None
    fine = np.angle(np.vdot(s1, s2)) / 64
    z = corrected[i:i+128] * np.exp(-1j*fine*np.arange(128))
    y = (np.fft.fft(z[:64]) + np.fft.fft(z[64:])) / 2
    h = y[K % 64] / X[K % 64]
    rssi = 10*np.log10(float(np.mean(np.abs(z)**2)) + 1e-20)
    return i, float(paired[i]), h, float((coarse+fine)*fs/(2*np.pi)), rssi


def extract(path, out, cfg, meta, log):
    path, out = Path(path), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if path.stat().st_size == 0 or path.stat().st_size % 2:
        raise ValueError(".cs8 harus non-kosong dan berisi pasangan int8 I,Q lengkap")
    raw = np.memmap(path, dtype=np.int8, mode="r")
    fs = cfg["fs_hz"]
    duration = len(raw) / (2*fs)
    # Count saturation in chunks; abs(int8(-128)) would overflow.
    clipped = 0
    histogram = np.zeros(256, dtype=np.int64)
    for start in range(0, len(raw), 2*cfg["chunk_samples"]):
        v = raw[start:start+2*cfg["chunk_samples"]]
        clipped += int(np.count_nonzero((v >= 127) | (v <= -127)))
        histogram += np.bincount(v.astype(np.int16)+128, minlength=256)
    np.savetxt(out/"adc_histogram.csv", np.column_stack((np.arange(-128, 128), histogram)),
               delimiter=",", fmt="%d", header="adc_value,component_count", comments="")
    times, cfos = [], []
    bursts = accepted = rejected_gate = 0
    occupied_samples = 0
    fields = ["t_s", "rssi_dbfs", "cfo_hz", "rho", *AMP,
              "label", "session_id", "subject_id"]
    with (out/"csi.csv").open("w", newline="") as f, (out/"bursts.csv").open("w", newline="") as bf:
        writer, bw = csv.writer(f), csv.writer(bf)
        writer.writerow(fields)
        bw.writerow(["start_s", "duration_us", "status", "rho", "cfo_hz", "rssi_dbfs"])
        for begin, end in burst_intervals(raw, cfg):
            bursts += 1
            occupied_samples += end-begin
            start = max(0, begin-40)
            seg = read_iq(raw, start, min(len(raw)//2, begin+640))
            result = estimate_ltf(seg, begin-start, fs)
            status = "no_ltf"
            rho = cfo = rssi = ""
            if result is not None:
                i, rho, h, cfo, rssi = result
                status = "low_rho"
                if rho > cfg["rho_min"]:
                    status = "accepted"
                    for key, value in (("cfo_range_hz", cfo), ("rssi_range_dbfs", rssi)):
                        gate = cfg[key]
                        if gate and not gate[0] <= value <= gate[1]:
                            status = "rejected_tx_gate"
                    if status == "accepted":
                        t = (start+i)/fs
                        writer.writerow([t, rssi, cfo, rho, *np.abs(h), meta.get("scenario", "unknown"),
                                         meta.get("session_id", "unknown"), meta.get("subject_id", "unknown")])
                        times.append(t)
                        cfos.append(cfo)
                        accepted += 1
                    else:
                        rejected_gate += 1
            bw.writerow([begin/fs, (end-begin)/fs*1e6, status, rho, cfo, rssi])
            if bursts % 1000 == 0:
                log.info("Bursts %s, CSI %s", bursts, accepted)
    gaps = np.diff([0, *times, duration])
    qc = {"duration_s": duration, "bursts": bursts, "valid_packets": accepted,
          "valid_burst_fraction": accepted/max(bursts, 1), "rejected_tx_gate": rejected_gate,
          "detected_burst_occupancy_fraction": occupied_samples/(len(raw)//2),
          "valid_packet_rate": accepted/duration, "max_gap_s": float(max(gaps)),
          "clipped_component_fraction": clipped/len(raw),
          "clipping_status": "pass" if clipped/len(raw) <= cfg["clip_fraction_max"] else "fail",
          "cfo_median_hz": float(np.median(cfos)) if cfos else None,
          "cfo_min_hz": float(min(cfos)) if cfos else None,
          "cfo_max_hz": float(max(cfos)) if cfos else None,
          "cfo_std_hz": float(np.std(cfos)) if cfos else None,
          "tx_verified": meta.get("tx_verified") is True,
          "timestamps": "sample_index/fs; USB dropped samples cannot be reconstructed"}
    qc["pilot_pass"] = (accepted >= cfg["pilot_min_packets"] and
                        qc["valid_packet_rate"] >= cfg["min_packet_rate"] and
                        qc["max_gap_s"] <= cfg["max_gap_s"] and qc["clipping_status"] == "pass")
    write_json(out/"qc.json", qc)
    write_json(out/"metadata.json", {**meta, "duration_s": duration, "qc": qc,
                                    "radio_config": cfg})
    return qc


def record(run, cfg, meta, duration):
    n = int(duration * cfg["fs_hz"])
    if n > 2**32-1:
        raise ValueError("Batasi satu capture < 2^32 sampel (sekitar 214 s pada 20 Msps)")
    raw = run.path / "capture.cs8"
    needed = 2*n + 200_000_000
    if shutil.disk_usage(run.path).free < needed:
        raise ValueError(f"Disk tidak cukup, perlu sekitar {needed/1e9:.2f} GB")
    cmd = ["hackrf_transfer", "-r", str(raw), "-f", str(cfg["center_freq_hz"]),
           "-s", str(cfg["fs_hz"]), "-b", "20000000", "-l", str(cfg["lna_db"]),
           "-g", str(cfg["vga_db"]), "-a", str(cfg["amplifier"]), "-n", str(n)]
    write_json(run.path/"capture_command.json", cmd)
    write_json(run.path/"metadata.json", meta)
    write_json(run.path/"capture_timing.json", {"host_start_unix_s": time.time(),
                                              "note": "host command start, not hardware timestamp"})
    run.log.info("RX-only command: %s", cmd)
    with (run.path/"hackrf.log").open("w") as f:
        process = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        try:
            code = process.wait(timeout=duration+30)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if code != 0:
        raise RuntimeError(f"hackrf_transfer exit {code}; lihat hackrf.log")
    if not raw.exists() or raw.stat().st_size != 2*n:
        raise RuntimeError("Capture parsial; ukuran tidak cocok jumlah sampel, lihat hackrf.log")
    run.input(raw)
    return extract(raw, run.path, cfg, meta, run.log)
