import multiprocessing
import sys

from .app import main

# Los modelos de IA se cargan en procesos aparte (multiprocessing «spawn»):
# esos procesos importan este módulo con otro nombre y no deben abrir la app.
if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
