"""Serialize native documents privately while preserving their logical filename."""

from pathlib import Path
from importlib import import_module
from types import SimpleNamespace
from typing import Any


def serialize_native(document: Any, staged: Path, target: Path, mode: str) -> None:
    adapter = getattr(document, "_sciplot_native_setting_batch_adapter", None)
    if adapter is not None:
        adapter.require_usable()
    if mode == "vsz" and callable(getattr(document, "saveToFile", None)):
        with staged.open("w", encoding="utf-8") as handle:
            # Veusz uses file.name only for linked source relativity. The byte
            # stream belongs to a private candidate, its scientific base stays
            # the explicitly selected native document location.
            document.saveToFile(SimpleNamespace(name=str(target), write=handle.write))
    elif mode == "hdf5" and callable(getattr(document, "saveToHDF5File", None)):
        h5py = import_module("veusz.document.doc").h5py

        if h5py is None:
            raise RuntimeError("Missing h5py module")
        with h5py.File(str(staged), "w") as handle:
            document.saveToHDF5File(SimpleNamespace(filename=str(target), create_group=handle.create_group))
    else:
        serializer = getattr(document, "_sciplot_original_native_save", document.save)
        serializer(str(staged), mode)
