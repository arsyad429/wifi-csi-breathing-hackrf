"""Offline amplitude pipeline; training-only carrier choice and paired RSSI metrics."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal
from scipy.ndimage import median_filter

from .radio import AMP, K
from .runlog import write_json


def load_trial(path, meta, cfg):
    df = pd.read_csv(path)
    required = ["t_s", "rssi_dbfs", "cfo_hz", "rho", *AMP]
    missing = set(required) - set(df)
    if missing:
        raise ValueError(f"Kolom CSI hilang: {sorted(missing)}")
    if not len(df):
        raise ValueError("CSV CSI kosong; periksa kanal, gain, dan deteksi L-LTF")
    if not np.isfinite(df[required].to_numpy(float)).all():
        raise ValueError("CSI berisi NaN/Inf")
    if (df.t_s < 0).any() or (df[AMP] < 0).any().any():
        raise ValueError("Timestamp/amplitudo harus nonnegatif")
    for column in ("session_id", "subject_id"):
        if column in df and set(df[column].astype(str)) != {str(meta.get(column))}:
            raise ValueError(f"{column} CSV dan metadata tidak cocok; jangan memindah identitas trial")
    if "label" in df and set(df.label.astype(str)) != {str(meta.get("scenario"))}:
        raise ValueError("label CSV dan scenario metadata tidak cocok")
    df = df.sort_values("t_s").drop_duplicates("t_s")
    df = df[df.rho > cfg["rho_min"]]
    for key, column in (("cfo_range_hz", "cfo_hz"), ("rssi_range_dbfs", "rssi_dbfs")):
        if cfg[key]:
            df = df[df[column].between(*cfg[key])]
    if len(df) < 3:
        raise ValueError("Kurang dari 3 paket lolos filter")
    duration = float(meta["duration_s"])
    if df.t_s.max() >= duration:
        raise ValueError("Timestamp di luar duration_s metadata")
    hz = cfg["resample_hz"]
    grid = np.arange(int(np.floor(duration*hz))) / hz
    t = df.t_s.to_numpy()
    values = df[[*AMP, "rssi_dbfs"]].to_numpy(float)
    # Hampel uses only this trial, without labels or cross-trial normalization.
    median = median_filter(values, size=(7, 1), mode="nearest")
    mad = median_filter(abs(values-median), size=(7, 1), mode="nearest")
    values = np.where(abs(values-median) > 3*1.4826*np.maximum(mad, 1e-8), median, values)
    regular = np.column_stack([np.interp(grid, t, values[:, k]) for k in range(53)])
    valid = np.ones(len(grid), dtype=bool)
    # Small boundary holds are explicit; long gaps are masked, never filtered across.
    for a, b in zip(np.r_[0, t], np.r_[t, duration]):
        if b-a > cfg["max_gap_s"]:
            valid[(grid >= a) & (grid <= b)] = False
    filtered = np.full_like(regular, np.nan)
    sos = signal.butter(cfg["filter_order"], cfg["bandpass_hz"],
                        btype="bandpass", fs=hz, output="sos")
    edges = np.diff(np.r_[False, valid, False].astype(int))
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if b-a < max(30, int(5*hz)):
            valid[a:b] = False
            continue
        filtered[a:b] = signal.sosfiltfilt(sos, signal.detrend(regular[a:b], axis=0), axis=0)
    gaps = np.diff(np.r_[0, t, duration])
    qc = {"valid_packets": len(df), "valid_packet_rate": len(df)/duration,
          "max_gap_s": float(gaps.max()), "duration_s": duration,
          "masked_grid_fraction": float(np.mean(~valid)),
          "boundary_hold_s": [float(t[0]), float(duration-t[-1])],
          "tx_verified": meta.get("tx_verified") is True,
          "clipping_status": meta.get("qc", {}).get("clipping_status", "unknown")}
    qc["quality_ok"] = (qc["valid_packet_rate"] >= cfg["min_packet_rate"] and
                         qc["tx_verified"] and qc["clipping_status"] == "pass")
    # No whole-trial gap veto: individual windows with gaps are rejected below.
    return {"path": str(path), "meta": meta, "df": df, "t": grid,
            "regular": regular, "filtered": filtered, "valid": valid, "qc": qc}


def spectra(trial, cfg):
    hz = cfg["resample_hz"]
    n = int(round(cfg["window_s"]*hz))
    hop = int(round(cfg["hop_s"]*hz))
    freq = np.fft.rfftfreq(n, 1/hz)
    band = (freq >= cfg["search_band_hz"][0]-1e-12) & (freq <= cfg["search_band_hz"][1]+1e-12)
    result = []
    for a in range(0, len(trial["t"])-n+1, hop):
        b = a+n
        packet_t = trial["df"].t_s.to_numpy()
        count = int(np.count_nonzero((packet_t >= a/hz) & (packet_t < b/hz)))
        ok = bool(trial["valid"][a:b].all() and trial["qc"]["quality_ok"] and
                  count/cfg["window_s"] >= cfg["min_packet_rate"])
        data = trial["filtered"][a:b]
        p = None
        if np.isfinite(data).all():
            p = abs(np.fft.rfft(data*np.hanning(n)[:, None], axis=0))**2
        result.append({"start_s": a/hz, "end_s": b/hz, "quality_ok": ok,
                       "packet_rate": count/cfg["window_s"], "power": p,
                       "freq": freq, "band": band})
    return result


def peak(power, freq, band):
    """Unpadded FFT: confidence = largest in-band bin / total in-band power."""
    if power is None:
        return None, 0.0, 0.0
    v = power[band]
    total = float(v.sum())
    if total <= 1e-18:
        return None, 0.0, total
    i = int(np.argmax(v))
    return float(freq[band][i]*60), float(v[i]/total), total


def select_carriers(training, cfg):
    scores = []
    for trial in training:
        if trial["meta"].get("scenario") != "breathing":
            continue
        for w in spectra(trial, cfg):
            if w["quality_ok"] and w["power"] is not None:
                scores.append([peak(w["power"][:, k], w["freq"], w["band"])[1]
                               for k in range(52)])
    if not scores:
        raise ValueError("Tidak ada jendela latih berkualitas untuk memilih subcarrier")
    scores = np.mean(scores, axis=0)
    order = np.argsort(-scores, kind="stable")
    return order[:cfg["aggregate_count"]], scores


def predict(trial, selected, cfg):
    rows = []
    fixed = int(np.flatnonzero(K == cfg["fixed_subcarrier"])[0])
    for w in spectra(trial, cfg):
        powers = {"csi_selected": None, "csi_fixed": None, "csi_median": None, "rssi": None}
        if w["power"] is not None:
            p = w["power"]
            # Median of normalized powers avoids cancellation across opposite phases.
            ps = p[:, selected]
            norm = np.maximum(ps[w["band"]].sum(axis=0), 1e-30)
            powers = {"csi_selected": p[:, selected[0]], "csi_fixed": p[:, fixed],
                      "csi_median": np.median(ps/norm, axis=1), "rssi": p[:, 52]}
        for method, p in powers.items():
            bpm, confidence, energy = peak(p, w["freq"], w["band"])
            reliable = bool(w["quality_ok"] and bpm is not None and confidence >= cfg["confidence_min"])
            reason = "ok" if reliable else ("packet_qc_or_tx_or_clipping" if not w["quality_ok"] else "weak_spectral_peak")
            m = trial["meta"]
            count = m.get("actual_breath_count")
            gt = float(count)*60/float(m["duration_s"]) if count is not None else None
            # Controls are never labeled as 0-BPM prediction targets.
            if m.get("scenario") != "breathing":
                gt = None
            rows.append({"trial_id": m.get("trial_id", Path(trial["path"]).parent.name),
                         "session_id": m.get("session_id", "unknown"),
                         "subject_id": m.get("subject_id", "unknown"),
                         "scenario": m.get("scenario"), "target_bpm": m.get("target_bpm"),
                         "orientation": m.get("orientation", "unspecified"),
                         "observed_motion": m.get("observed_motion", ""),
                         "ground_truth_bpm": gt, "start_s": w["start_s"], "end_s": w["end_s"],
                         "method": method, "peak_bpm": bpm,
                         "pred_bpm": bpm if reliable and m.get("scenario") == "breathing" else None,
                         "confidence": confidence, "band_power": energy,
                         "reliable": reliable, "reason": reason,
                         "selected_k": int(K[selected[0]]), "packet_rate": w["packet_rate"]})
    return rows


def trial_plots(trial, out, selected, cfg):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    carrier = int(selected[0])
    prefix = "[DATA SINTETIS] " if trial["meta"].get("synthetic") is True else ""
    fig, ax = plt.subplots(2, 1, figsize=(10, 6), constrained_layout=True)
    ax[0].plot(trial["df"].t_s, trial["df"][AMP[carrier]], lw=.6)
    ax[0].set(ylabel=f"|H[{K[carrier]}]|", title=f"{prefix}{trial['meta'].get('trial_id', '')} — amplitudo CSI")
    ax[1].plot(trial["t"], trial["filtered"][:, carrier], lw=.8)
    ax[1].set(xlabel="Waktu (s)", ylabel="CSI band-pass")
    fig.savefig(out/"amplitude.png", dpi=140)
    plt.close(fig)
    windows = [w for w in spectra(trial, cfg) if w["power"] is not None]
    fig, ax = plt.subplots(figsize=(9, 4), constrained_layout=True)
    if windows:
        w = windows[0]
        for name, idx in ((f"CSI k={K[carrier]}", carrier), ("RSSI", 52)):
            p = w["power"][:, idx]
            line, = ax.plot(w["freq"]*60, p/max(float(p.max()), 1e-30), label=name)
            bpm, confidence, _ = peak(p, w["freq"], w["band"])
            if bpm is not None:
                ax.axvline(bpm, ls="--", color=line.get_color(), alpha=.5, label=f"{name}: {bpm:.1f} BPM, C={confidence:.2f}")
        ax.set_title(f"{prefix}FFT {cfg['window_s']:g} s; QC {'lolos' if w['quality_ok'] else 'gagal'}")
        ax.legend(fontsize=8)
    else:
        ax.text(.5, .5, "Tidak tersedia jendela FFT 30 s yang utuh", ha="center", transform=ax.transAxes)
        ax.set_title(prefix + "Kontrol singkat / data tidak utuh")
    ax.set(xlabel="Frekuensi (BPM)", ylabel="Daya relatif", xlim=(0, 36))
    fig.savefig(out/"spectrum.png", dpi=140)
    plt.close(fig)


def save_analysis(trial, out, selected, cfg):
    out = Path(out)
    rows = predict(trial, selected, cfg)
    pd.DataFrame(rows).to_csv(out/"predictions.csv", index=False)
    pd.DataFrame({"t_s": trial["t"], "valid_grid": trial["valid"],
                  **{name: trial["filtered"][:, i] for i, name in enumerate([*AMP, "rssi_dbfs"])}}
                 ).to_csv(out/"preprocessed.csv", index=False)
    write_json(out/"qc.json", trial["qc"])
    energy = np.nanmean(trial["filtered"]**2, axis=0) if np.isfinite(trial["filtered"]).any() else np.full(53, np.nan)
    write_json(out/"control_energy.json", {
        "scenario": trial["meta"].get("scenario"),
        "filtered_mean_square_csi_selected": float(energy[selected[0]]) if np.isfinite(energy[selected[0]]) else None,
        "filtered_mean_square_rssi": float(energy[52]) if np.isfinite(energy[52]) else None,
        "note": "Energi relatif; 15 s terlalu singkat untuk FFT utama/apnea klinis. Edge transient dapat dominan."})
    trial_plots(trial, out, selected, cfg)
    return rows


def evaluate(trials, out, cfg, group="session_id"):
    out = Path(out)
    groups = sorted({str(t["meta"][group]) for t in trials if t["meta"].get("scenario") == "breathing"})
    if len(groups) < 2:
        raise ValueError(f"Evaluasi perlu >=2 kelompok {group}; rancangan utama memakai 3")
    rows, folds = [], []
    for held in groups:
        train = [t for t in trials if str(t["meta"][group]) != held]
        test = [t for t in trials if str(t["meta"][group]) == held]
        selected, scores = select_carriers(train, cfg)
        folds.append({"held_out": held, "group": group, "selected_k": K[selected].tolist(),
                      "training_trials": [t["meta"]["trial_id"] for t in train],
                      "test_trials": [t["meta"]["trial_id"] for t in test],
                      "scores": dict(zip(map(str, K), map(float, scores)))})
        for trial in test:
            for row in predict(trial, selected, cfg):
                rows.append({**row, "fold": held})
            trial_plots(trial, out/"plots"/trial["meta"]["trial_id"], selected, cfg)
    write_json(out/"folds.json", folds)
    df = pd.DataFrame(rows)
    df.to_csv(out/"predictions.csv", index=False)
    labeled = df[(df.scenario == "breathing") & df.ground_truth_bpm.notna()].copy()
    # Pair each CSI method with RSSI on identical trial/window keys.
    keys = ["fold", "trial_id", "start_s", "end_s"]
    rr = labeled[labeled.method == "rssi"]
    metrics, paired_rows = [], []
    for method in ("csi_selected", "csi_fixed", "csi_median"):
        cc = labeled[labeled.method == method]
        pair = cc.merge(rr[keys+["pred_bpm", "reliable"]], on=keys, suffixes=("", "_rssi"))
        pair = pair[pair.reliable & pair.reliable_rssi].copy()
        pair["error_csi"] = pair.pred_bpm - pair.ground_truth_bpm
        pair["error_rssi"] = pair.pred_bpm_rssi - pair.ground_truth_bpm
        paired_rows.append(pair)
        for by in ([], ["target_bpm"], ["subject_id"], ["session_id"], ["fold"], ["orientation"]):
            chunks = [("all", pair)] if not by else pair.groupby(by[0], dropna=False)
            for value, part in chunks:
                metrics.append({"method": method, "group": by[0] if by else "all", "value": value,
                                "n_paired": len(part), "mae_csi": float(part.error_csi.abs().mean()) if len(part) else None,
                                "mae_rssi": float(part.error_rssi.abs().mean()) if len(part) else None,
                                "bias_csi": float(part.error_csi.mean()) if len(part) else None,
                                "bias_rssi": float(part.error_rssi.mean()) if len(part) else None,
                                "delta_mae_csi_minus_rssi": float(part.error_csi.abs().mean()-part.error_rssi.abs().mean()) if len(part) else None})
    mt = pd.DataFrame(metrics)
    mt.to_csv(out/"metrics_paired.csv", index=False)
    pairs = pd.concat(paired_rows, ignore_index=True)
    pairs.to_csv(out/"paired_windows.csv", index=False)
    coverage = []
    for method, part in df[df.scenario == "breathing"].groupby("method"):
        ok = part[part.reliable & part.ground_truth_bpm.notna()]
        coverage.append({"method": method, "n_windows": len(part), "n_reliable": int(part.reliable.sum()),
                         "reliable_fraction": float(part.reliable.mean()), "n_labeled_reliable": len(ok),
                         "mae_own_valid": float((ok.pred_bpm-ok.ground_truth_bpm).abs().mean()) if len(ok) else None})
    pd.DataFrame(coverage).to_csv(out/"coverage.csv", index=False)
    fig, ax = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    if all(t["meta"].get("synthetic") is True for t in trials):
        fig.suptitle("DATA SINTETIS — verifikasi pipeline, bukan hasil eksperimen manusia")
    main = pairs[pairs.method == "csi_selected"]
    if len(main):
        ax[0].scatter(main.ground_truth_bpm, main.pred_bpm, label="CSI", alpha=.7)
        ax[0].scatter(main.ground_truth_bpm, main.pred_bpm_rssi, label="RSSI", alpha=.5)
        ax[0].plot([6, 30], [6, 30], "k--", lw=.7)
        ax[0].legend()
    else:
        ax[0].text(.5, .5, "Tidak ada pasangan estimasi andal", ha="center", transform=ax[0].transAxes)
    ax[0].set(xlabel="Ground truth rata-rata trial (BPM)", ylabel="Prediksi jendela (BPM)")
    by_rate = mt[(mt.method == "csi_selected") & (mt.group == "target_bpm")]
    if len(by_rate):
        x = np.arange(len(by_rate))
        ax[1].bar(x-.18, by_rate.mae_csi, width=.36, label="CSI")
        ax[1].bar(x+.18, by_rate.mae_rssi, width=.36, label="RSSI")
        ax[1].set_xticks(x, by_rate.value.astype(str))
        ax[1].legend()
    ax[1].set(xlabel="Target BPM", ylabel="MAE pada pasangan jendela (BPM)")
    fig.savefig(out/"evaluation.png", dpi=140)
    plt.close(fig)
    qcs = [{"trial_id": t["meta"]["trial_id"], **t["qc"]} for t in trials]
    pd.DataFrame(qcs).to_csv(out/"quality.csv", index=False)
    controls = []
    for trial in trials:
        if trial["meta"].get("scenario") not in ("empty", "breath_hold"):
            continue
        energy = (np.nanmean(trial["filtered"]**2, axis=0)
                  if np.isfinite(trial["filtered"]).any() else np.full(53, np.nan))
        controls.append({"trial_id": trial["meta"]["trial_id"],
                         "scenario": trial["meta"]["scenario"], "duration_s": trial["meta"]["duration_s"],
                         "energy_csi_fixed": energy[fixed_index(cfg)], "energy_rssi": energy[52],
                         "quality_ok": trial["qc"]["quality_ok"],
                         "note": "Energi relatif carrier tetap; kontrol singkat rentan edge transient; bukan apnea"})
    pd.DataFrame(controls, columns=["trial_id", "scenario", "duration_s", "energy_csi_fixed",
                                   "energy_rssi", "quality_ok", "note"]).to_csv(out/"controls.csv", index=False)
    write_json(out/"summary.json", {"split": group, "n_folds": len(groups), "n_trials": len(trials),
        "synthetic": all(t["meta"].get("synthetic") is True for t in trials),
        "all_labeled": bool(df[df.scenario == "breathing"].ground_truth_bpm.notna().all()),
        "metrics": mt[mt.group == "all"].astype(object).where(pd.notna(mt), None).to_dict("records"),
        "note": "Jendela overlap bukan observasi independen. GT hitung manual adalah rata-rata trial, bukan GT per jendela."})
    return mt


def fixed_index(cfg):
    return int(np.flatnonzero(K == cfg["fixed_subcarrier"])[0])
