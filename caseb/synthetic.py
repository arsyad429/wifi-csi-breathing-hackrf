"""Data rekayasa untuk verifikasi numerik, bukan data eksperimen manusia."""
from pathlib import Path

import numpy as np
import pandas as pd

from .radio import AMP, K, LTF, X
from .runlog import write_json


def make_iq(path, duration=1.0, packet_rate=25, cfo_hz=220000, seed=7, starts=None):
    fs = 20_000_000
    rng = np.random.default_rng(seed)
    n = int(duration*fs)
    raw = np.memmap(path, mode="w+", dtype=np.int8, shape=(2*n,))
    for a in range(0, 2*n, 2_000_000):
        raw[a:a+2_000_000] = np.clip(np.rint(rng.normal(0, .65, min(2_000_000, 2*n-a))), -128, 127).astype(np.int8)
    # A known short multipath channel, with true legacy LTF. The STF is a
    # deterministic periodic training stand-in, not a complete Wi-Fi PHY encoder.
    channel = np.zeros(64, complex)
    channel[0], channel[3], channel[7] = 1.8, .25+.1j, -.12j
    h = np.fft.fft(channel)
    symbol = np.fft.ifft(X*h)
    short = (rng.choice([-1, 1], 16) + 1j*rng.choice([-1, 1], 16)) * .12
    stf = np.tile(short, 10)
    tail = rng.normal(0, .12, 240) + 1j*rng.normal(0, .12, 240)
    frame = np.r_[stf, symbol[-32:], symbol, symbol, tail]
    frame *= np.exp(2j*np.pi*cfo_hz*np.arange(len(frame))/fs)
    if starts is None:
        starts = (np.arange(packet_rate*int(duration))+.25)/packet_rate*fs
    actual = []
    for start in map(int, starts):
        if start+len(frame) >= n:
            continue
        noise = (rng.normal(0, .003, len(frame)) + 1j*rng.normal(0, .003, len(frame)))
        f = frame+noise
        raw[2*start:2*(start+len(f)):2] = np.clip(np.rint(f.real*128), -128, 127).astype(np.int8)
        raw[2*start+1:2*(start+len(f)):2] = np.clip(np.rint(f.imag*128), -128, 127).astype(np.int8)
        actual.append(start/fs)
    raw.flush()
    del raw
    return {"cfo_hz": cfo_hz, "amplitude": np.abs(h[K % 64]).tolist(), "packet_start_s": actual,
            "description": "SYNTHETIC; true LTF, periodic STF stand-in, known short channel; no valid MAC/payload"}


def make_dataset(out, seed=7):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    entries = []
    scenarios = [(s, p, bpm, "breathing", 60) for s in ("S1", "S2", "S3")
                 for p in ("P1", "P2", "P3") for bpm in (10, 15, 20)]
    scenarios += [(s, "none", None, "empty", 60) for s in ("S1", "S2", "S3")]
    scenarios += [("S1", p, None, "breath_hold", 15) for p in ("P1", "P2", "P3")]
    for s, p, bpm, scenario, duration in scenarios:
        trial_id = f"B_{s}_{p}_{bpm if bpm else scenario}"
        folder = out/trial_id
        folder.mkdir()
        t = np.arange(.03, duration, .08)
        t += rng.uniform(-.006, .006, len(t))
        f = (bpm or 15)/60
        phase = rng.uniform(-np.pi, np.pi, 52)
        sensitivity = .01 + .12*np.exp(-((K-8)/7)**2)
        amplitudes = 1 + .15*np.cos(K/8)[None, :] + rng.normal(0, .015, (len(t), 52))
        if scenario == "breathing":
            amplitudes += sensitivity[None, :]*np.sin(2*np.pi*f*t[:, None]+phase)
        rssi = -24 + rng.normal(0, .15, len(t)) + .25*np.sin(2*np.pi*.4*t)
        if scenario == "breathing":
            rssi += .04*np.sin(2*np.pi*f*t)
        df = pd.DataFrame(amplitudes, columns=AMP)
        df.insert(0, "rho", .95)
        df.insert(0, "cfo_hz", rng.normal(22000, 200, len(t)))
        df.insert(0, "rssi_dbfs", rssi)
        df.insert(0, "t_s", t)
        df["label"], df["session_id"], df["subject_id"] = scenario, s, p
        df.to_csv(folder/"csi.csv", index=False)
        meta = {"trial_id": trial_id, "session_id": s, "subject_id": p, "scenario": scenario,
                "duration_s": duration, "target_bpm": bpm, "actual_breath_count": bpm,
                "synthetic": True, "tx_verified": True,
                "tx_verification_note": "synthetic single-source fixture",
                "qc": {"clipping_status": "pass"}, "note": "DATA SINTETIS; bukan pengukuran manusia"}
        write_json(folder/"metadata.json", meta)
        entries.append({"trial_id": trial_id, "csi_path": f"{trial_id}/csi.csv",
                        "metadata_path": f"{trial_id}/metadata.json"})
    pd.DataFrame(entries).to_csv(out/"dataset.csv", index=False)
    write_json(out/"SYNTHETIC.json", {"seed": seed, "warning": "Bukan hasil eksperimen. RSSI interference sengaja dibuat untuk uji alur evaluasi; tidak membuktikan H1."})
    return out/"dataset.csv"
