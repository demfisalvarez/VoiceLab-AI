"""Punto de entrada del ejecutable (PyInstaller)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()     # los procesos de IA arrancan con el mismo .exe
    from voicelab.app import main
    sys.exit(main())
