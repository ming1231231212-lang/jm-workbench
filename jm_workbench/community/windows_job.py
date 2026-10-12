"""Own a suspended child before it can spawn drivers; never attach user Chrome.

Windows 10/11 Job Objects terminate the complete owned process tree directly.
KILL_ON_JOB_CLOSE also protects against the service itself exiting unexpectedly.
"""
import ctypes
from ctypes import wintypes as w
import threading


class BasicLimits(ctypes.Structure):
    _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),
        ('min_working_set',ctypes.c_size_t),('max_working_set',ctypes.c_size_t),
        ('active_processes',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_=[(name,ctypes.c_uint64) for name in ('read_operations','write_operations','other_operations','read_bytes','write_bytes','other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_=[('basic',BasicLimits),('io',IoCounters),('process_memory',ctypes.c_size_t),
        ('job_memory',ctypes.c_size_t),('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]


class ThreadEntry(ctypes.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('ident',w.DWORD),('owner',w.DWORD),
        ('base_priority',w.LONG),('delta_priority',w.LONG),('flags',w.DWORD)]


class OwnedJob:
    def __init__(self, child):
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.lock=threading.Lock();self.handle=None
        definitions={
          'CreateJobObjectW':([ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
          'SetInformationJobObject':([w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
          'AssignProcessToJobObject':([w.HANDLE,w.HANDLE],w.BOOL),
          'TerminateJobObject':([w.HANDLE,w.UINT],w.BOOL),
          'CloseHandle':([w.HANDLE],w.BOOL),
          'CreateToolhelp32Snapshot':([w.DWORD,w.DWORD],w.HANDLE),
          'Thread32First':([w.HANDLE,ctypes.POINTER(ThreadEntry)],w.BOOL),
          'Thread32Next':([w.HANDLE,ctypes.POINTER(ThreadEntry)],w.BOOL),
          'OpenThread':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
          'ResumeThread':([w.HANDLE],w.DWORD),
        }
        for name,(args,result) in definitions.items():
            function=getattr(self.kernel,name);function.argtypes=args;function.restype=result
        try:
            self.handle=self.kernel.CreateJobObjectW(None,None)
            if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
            limits=ExtendedLimits();limits.basic.flags=0x2000 # KILL_ON_JOB_CLOSE, no breakaway
            if not self.kernel.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.kernel.AssignProcessToJobObject(self.handle,int(child._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.resume(child.pid)
        except Exception:
            self.close();raise

    def resume(self,pid):
        snapshot=self.kernel.CreateToolhelp32Snapshot(4,0) # TH32CS_SNAPTHREAD
        if snapshot in (None,ctypes.c_void_p(-1).value):raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry=ThreadEntry();entry.size=ctypes.sizeof(entry)
            valid=self.kernel.Thread32First(snapshot,ctypes.byref(entry))
            while valid:
                if entry.owner==pid:
                    thread=self.kernel.OpenThread(2,False,entry.ident) # THREAD_SUSPEND_RESUME
                    if not thread:raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.kernel.ResumeThread(thread)!=1:raise RuntimeError('本次任务没有保持启动暂停状态')
                    finally:self.kernel.CloseHandle(thread)
                    return
                valid=self.kernel.Thread32Next(snapshot,ctypes.byref(entry))
            raise RuntimeError('未找到本次任务的启动线程')
        finally:self.kernel.CloseHandle(snapshot)

    def terminate(self):
        with self.lock:
            if self.handle and not self.kernel.TerminateJobObject(self.handle,1):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        with self.lock:
            if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None
