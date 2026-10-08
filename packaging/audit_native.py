"""Report native libraries loaded from a machine outside the shipped runtime."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys

import cv2
import numpy
import greenlet
import pydantic_core
import lxml.etree

modules=(ctypes.c_void_p*4096)()
needed=wintypes.DWORD()
handle=ctypes.windll.kernel32.GetCurrentProcess()
ctypes.windll.psapi.EnumProcessModulesEx.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),wintypes.DWORD]
ctypes.windll.psapi.EnumProcessModulesEx(handle,modules,ctypes.sizeof(modules),ctypes.byref(needed),3)
ctypes.windll.psapi.GetModuleFileNameExW.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.LPWSTR,wintypes.DWORD]
root=Path(sys.executable).parent.resolve()
for module in modules[:needed.value//ctypes.sizeof(ctypes.c_void_p)]:
    buffer=ctypes.create_unicode_buffer(32768)
    ctypes.windll.psapi.GetModuleFileNameExW(handle,module,buffer,len(buffer))
    path=Path(buffer.value)
    if any(key in path.name.lower() for key in ('msvcp','vcruntime','concrt')):
        print(('BUNDLED' if path.resolve().is_relative_to(root) else 'EXTERNAL')+' '+str(path))
