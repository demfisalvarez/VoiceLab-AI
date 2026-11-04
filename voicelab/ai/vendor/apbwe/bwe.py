"""AP-BWE (Ye-Xin Lu et al., 2024, licencia MIT): amplía el ancho de banda de 16 kHz a 48 kHz.

Arquitectura copiada de https://github.com/yxlu-0102/AP-BWE (commit 751710f, ``models/model.py`` y
``datasets/dataset.py``), reducida al generador. Lo propio de VoiceLab es :class:`StreamingBWE`, que lo
aplica por bloques con contexto para usarlo en directo.

Solo se importa en el proceso de la voz en directo (necesita PyTorch).
"""

from __future__ import annotations

import json
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


class ConvNeXtBlock(nn.Module):
    def __init__(self, dim: int, layer_scale_init_value: float):
        super().__init__()
        self.dwconv = nn.Conv1d(dim, dim, kernel_size=7, padding=3, groups=dim)
        self.norm = nn.LayerNorm(dim, eps=1e-6)
        self.pwconv1 = nn.Linear(dim, dim * 3)
        self.act = nn.GELU()
        self.pwconv2 = nn.Linear(dim * 3, dim)
        self.gamma = nn.Parameter(layer_scale_init_value * torch.ones(dim)) if layer_scale_init_value > 0 else None

    def forward(self, x):
        residual = x
        x = self.dwconv(x).transpose(1, 2)
        x = self.pwconv2(self.act(self.pwconv1(self.norm(x))))
        if self.gamma is not None:
            x = self.gamma * x
        return residual + x.transpose(1, 2)


class APNetBWE(nn.Module):
    def __init__(self, h: dict):
        super().__init__()
        ch, n_bins, layers = h["ConvNeXt_channels"], h["n_fft"] // 2 + 1, h["ConvNeXt_layers"]
        self.conv_pre_mag = nn.Conv1d(n_bins, ch, 7, 1, padding=3)
        self.norm_pre_mag = nn.LayerNorm(ch, eps=1e-6)
        self.conv_pre_pha = nn.Conv1d(n_bins, ch, 7, 1, padding=3)
        self.norm_pre_pha = nn.LayerNorm(ch, eps=1e-6)
        self.convnext_mag = nn.ModuleList([ConvNeXtBlock(ch, 1 / layers) for _ in range(layers)])
        self.convnext_pha = nn.ModuleList([ConvNeXtBlock(ch, 1 / layers) for _ in range(layers)])
        self.norm_post_mag = nn.LayerNorm(ch, eps=1e-6)
        self.norm_post_pha = nn.LayerNorm(ch, eps=1e-6)
        self.linear_post_mag = nn.Linear(ch, n_bins)
        self.linear_post_pha_r = nn.Linear(ch, n_bins)
        self.linear_post_pha_i = nn.Linear(ch, n_bins)

    def forward(self, mag_nb, pha_nb):
        x_mag = self.norm_pre_mag(self.conv_pre_mag(mag_nb).transpose(1, 2)).transpose(1, 2)
        x_pha = self.norm_pre_pha(self.conv_pre_pha(pha_nb).transpose(1, 2)).transpose(1, 2)
        for bm, bp in zip(self.convnext_mag, self.convnext_pha):
            x_mag = x_mag + x_pha
            x_pha = x_pha + x_mag
            x_mag = bm(x_mag)
            x_pha = bp(x_pha)
        x_mag = self.norm_post_mag(x_mag.transpose(1, 2))
        mag_wb = mag_nb + self.linear_post_mag(x_mag).transpose(1, 2)
        x_pha = self.norm_post_pha(x_pha.transpose(1, 2))
        pha_wb = torch.atan2(self.linear_post_pha_i(x_pha), self.linear_post_pha_r(x_pha)).transpose(1, 2)
        return mag_wb, pha_wb


def load(ckpt: str, config: str | None = None) -> tuple[APNetBWE, dict]:
    h = json.loads(open(config or os.path.join(os.path.dirname(__file__), "config_16kto48k.json")).read())
    model = APNetBWE(h)
    state = torch.load(ckpt, map_location="cpu", weights_only=True)
    state = state.get("generator", state)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing:
        raise RuntimeError(f"Los pesos de AP-BWE no encajan: faltan {missing[:4]}")
    model.eval()
    return model, h


class Upsample3:
    """16 kHz → 48 kHz por bloques (FIR polifásico con estado), solo con numpy."""

    def __init__(self, taps_per_phase: int = 32, beta: float = 8.0):
        n = 3 * taps_per_phase
        t = np.arange(n) - (n - 1) / 2
        h = np.sinc(t / 3 * 0.94) * 0.94 * np.kaiser(n, beta)          # corte justo por debajo de 8 kHz
        self.poly = h.reshape(taps_per_phase, 3).T[:, ::-1].astype(np.float32)   # (3, taps)
        self.taps = taps_per_phase
        self.hist = np.zeros(taps_per_phase - 1, np.float32)
        self.delay = (n - 1) / 2                                         # en muestras de salida

    def process(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.hist, x.astype(np.float32)])
        win = np.lib.stride_tricks.sliding_window_view(buf, self.taps)  # (len(x), taps)
        y = (win @ self.poly.T).reshape(-1)                              # intercala las 3 fases
        self.hist = buf[-(self.taps - 1):]
        return y.astype(np.float32)


class StreamingBWE:
    """Aplica AP-BWE por bloques: entra audio a 16 kHz y sale a 48 kHz.

    El modelo es convolucional con un campo receptivo de ±27 tramas (±45 ms). Cada trozo se calcula con
    contexto a la izquierda (lo ya oído) y un poco a la derecha; esa parte derecha se retiene y se vuelve a
    calcular con el siguiente trozo, uniendo ambos con un fundido. Retraso añadido: ``rctx + fade``.
    """

    def __init__(self, model: APNetBWE, h: dict, lctx_s: float = 0.05, rctx_s: float = 0.02, fade_s: float = 0.005):
        self.m, self.h = model, h
        self.sr = h["hr_sampling_rate"]
        self.n_fft, self.hop, self.win = h["n_fft"], h["hop_size"], h["win_size"]
        self.lctx = int(lctx_s * self.sr) // self.hop * self.hop
        self.rctx = int(rctx_s * self.sr) // self.hop * self.hop
        self.fade = int(fade_s * self.sr)
        self.window = torch.hann_window(self.win)
        self.latency = self.rctx + self.fade                              # muestras a 48 kHz
        self.reset()

    def reset(self) -> None:
        self.up = Upsample3()
        self.left = np.zeros(self.lctx, np.float32)
        self.pending = np.zeros(0, np.float32)
        self.tail: np.ndarray | None = None

    @torch.no_grad()
    def run_full(self, x48: np.ndarray) -> np.ndarray:
        t = torch.from_numpy(np.ascontiguousarray(x48, np.float32)).unsqueeze(0)
        spec = torch.stft(t, self.n_fft, hop_length=self.hop, win_length=self.win, window=self.window,
                          center=True, pad_mode="reflect", return_complex=True)
        mag, pha = self.m(torch.log(spec.abs() + 1e-4), torch.angle(spec))
        com = torch.complex(torch.exp(mag) * torch.cos(pha), torch.exp(mag) * torch.sin(pha))
        y = torch.istft(com, self.n_fft, hop_length=self.hop, win_length=self.win, window=self.window,
                        center=True, length=x48.shape[0])
        return y.squeeze(0).numpy()

    def process(self, x16: np.ndarray) -> np.ndarray:
        """Entra audio a 16 kHz (cualquier tamaño); sale el audio a 48 kHz que ya está listo."""
        self.pending = np.concatenate([self.pending, self.up.process(x16)])
        hold = self.rctx + self.fade
        n = (self.pending.shape[0] - hold) // self.hop * self.hop         # lo que se puede emitir ya
        if n <= 0:
            return np.zeros(0, np.float32)
        seg = np.concatenate([self.left, self.pending[: n + hold]])
        y = self.run_full(seg)[self.lctx:]                                # n + hold muestras
        out = y[:n].copy()
        if self.tail is not None:
            k = min(self.fade, out.shape[0])
            ramp = np.linspace(0.0, 1.0, k, dtype=np.float32)
            out[:k] = self.tail[:k] * (1 - ramp) + out[:k] * ramp
        self.tail = y[n: n + self.fade].copy()
        self.left = np.concatenate([self.left, self.pending[:n]])[-self.lctx:]
        self.pending = self.pending[n:]
        return out
