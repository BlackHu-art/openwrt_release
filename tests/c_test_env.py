"""Compile isolated C regression harnesses with GCC/Clang or installed MSVC."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile


def msvc_environment_script(environment):
    """Find the installed C++ toolchain without changing the caller's environment."""
    base = environment.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    vswhere = Path(base) / "Microsoft Visual Studio/Installer/vswhere.exe"
    if not vswhere.is_file():
        return None
    result = subprocess.run([str(vswhere), "-latest", "-products", "*", "-requires",
                             "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                             "-property", "installationPath"],
                            capture_output=True, text=True, timeout=20, env=environment)
    if result.returncode or not result.stdout.strip():
        return None
    script = Path(result.stdout.strip()) / "VC/Auxiliary/Build/vcvars64.bat"
    return script if script.is_file() else None


def compile_c(source, output, environment=None):
    """Compile or fail explicitly; lack of a compiler never skips runtime tests."""
    environment = dict(os.environ if environment is None else environment)
    configured = environment.get("CC")
    command = ([configured] if configured and Path(configured).is_file()
               else shlex.split(configured) if configured else [])
    if not command:
        found = next((shutil.which(name, path=environment.get("PATH"))
                      for name in ("cc", "gcc", "clang")
                      if shutil.which(name, path=environment.get("PATH"))), None)
        if found:
            command = [found]
    if command:
        result = subprocess.run(command + ["-std=c99", "-Wall", "-Wextra", "-Wno-sign-compare",
                                           str(source), "-o", str(output)],
                                capture_output=True, text=True, timeout=60, env=environment)
    else:
        vcvars = msvc_environment_script(environment) if os.name == "nt" else None
        if not vcvars:
            raise RuntimeError("C compiler required: install GCC/Clang or MSVC C++ Build Tools, or set CC")
        # Only this short-lived compiler process loads vcvars. The batch contains
        # trusted toolchain and tempfile paths, never packet data or user input.
        with tempfile.TemporaryDirectory(prefix="oaf-msvc-") as directory:
            batch = Path(directory) / "compile.cmd"
            obj = Path(directory) / "harness.obj"
            batch.write_text('@echo off\ncall "' + str(vcvars) + '" >nul\n'
                             'if errorlevel 1 exit /b %errorlevel%\n'
                             'cl /nologo /std:c11 /W3 /D_CRT_SECURE_NO_WARNINGS "' + str(source) +
                             '" /Fe:"' + str(output) + '" /Fo:"' + str(obj) + '"\n', encoding="utf-8")
            result = subprocess.run([environment.get("COMSPEC", "cmd.exe"), "/d", "/c", str(batch)],
                                    capture_output=True, text=True, timeout=60, env=environment)
    if result.returncode:
        raise RuntimeError("C harness did not compile:\n" + result.stdout + result.stderr)
    return result
