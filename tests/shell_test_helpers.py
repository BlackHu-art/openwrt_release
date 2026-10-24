"""Portable Git Bash boundaries shared by shell integration tests."""
import os
from pathlib import Path
import shutil


def bash_path(path):
    path = Path(path).resolve().as_posix()
    return "/" + path[0].lower() + path[2:] if os.name == "nt" else path


def bash_executable():
    return os.environ.get("BASH") or shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
