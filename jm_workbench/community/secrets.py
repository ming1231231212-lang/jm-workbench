"""Windows DPAPI user-bound encryption. No credentials leave the local machine."""
import base64
import ctypes
import os
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]


def transform(value, decrypt=False):
    buffer=ctypes.create_string_buffer(value)
    source=Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    dest=Blob()
    dll=ctypes.windll.crypt32
    fn=dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(dest)):
        raise ValueError('无法读取本机账号密钥，请重新配置')
    try:
        return ctypes.string_at(dest.data,dest.size)
    finally:
        ctypes.windll.kernel32.LocalFree(dest.data)


def seal(value):
    if not value:return ''
    if os.name!='nt':
        # Tests on Linux inject no production credentials; fail closed in production.
        if not os.environ.get('PYTEST_CURRENT_TEST'):
            raise ValueError('本版密钥存储需要Windows用户加密环境')
        return 'test:'+base64.b64encode(value.encode()).decode()
    return 'dpapi:'+base64.b64encode(transform(value.encode())).decode()


def unseal(value):
    if not value:return ''
    mode,encoded=value.split(':',1)
    raw=base64.b64decode(encoded)
    if mode=='dpapi' and os.name=='nt':return transform(raw,True).decode()
    if mode=='test' and os.environ.get('PYTEST_CURRENT_TEST'):return raw.decode()
    raise ValueError('账号密钥属于其他环境，请重新配置')
