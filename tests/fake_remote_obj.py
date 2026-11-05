"""Objeto de prueba para ``procs.Remote`` (se importa en el proceso hijo)."""
import os
import time

import numpy as np


class Stop(RuntimeError):
    cancelled = True


class Obj:
    def __init__(self, mode, stage, cancel):
        stage("cargando 1/2")
        if mode == "fail_load":
            raise RuntimeError("DirectML: el dispositivo se ha eliminado")
        if mode == "crash_load":
            os._exit(5)
        if mode == "hang_load":
            time.sleep(60)
        stage("cargando 2/2")
        self.mode, self.cancel = mode, cancel
        self.info = {"device": "gpu" if mode.startswith("gpu") else "cpu", "sr": 40000, "style": "webui"}

    def work(self, n, progress=None):
        for i in range(n):
            if self.cancel.is_set():
                raise Stop("cancelado")
            time.sleep(0.01)
            if progress:
                progress(i / n)
        return np.arange(n)

    def stubborn(self):
        while True:                      # no atiende la cancelación ni da noticias
            time.sleep(0.1)

    def crash(self):
        os._exit(7)

    def boom(self):
        raise ValueError("algo ha ido mal")

    def synthesize(self, *args, progress=None):
        if self.mode == "gpu_crash":
            os._exit(9)
        if progress:
            progress(0.5)
        return np.ones(10, np.float32)

    def convert16(self, x16, semitones=0.0, keep=0):
        return np.asarray(x16, np.float32) * 2


def make(mode, stage=None, cancel=None):
    return Obj(mode, stage, cancel)


def make_rvc(target, kind="profile", prefer_gpu=True, stage=None, cancel=None):
    return Obj("gpu_crash" if prefer_gpu and "gpu_fail" in target else ("gpu" if prefer_gpu else "cpu"), stage, cancel) \
        if "gpu_fail" not in target or not prefer_gpu else make("fail_load", stage, cancel)
