"""Windows process identity, self-memory and non-breakaway job containment.

Standard library only. Importing this module starts no process and loads no DLL.
The retained handles identify process objects even after PID reuse. This module
does not implement a kernel hard memory ceiling or claim continuous sampling.
"""
from __future__ import annotations

import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

DWORD = ct.c_uint32
LONG = ct.c_int32
HANDLE = ct.c_void_p
SIZE_T = ct.c_size_t
BOOL = ct.c_int
ULONG64 = ct.c_uint64


class ObserverError(RuntimeError):
    pass


class UnsupportedPlatform(ObserverError):
    pass


class FILETIME(ct.Structure):
    _fields_ = [("low", DWORD), ("high", DWORD)]


class MEMORY_COUNTERS(ct.Structure):
    _fields_ = [("cb", DWORD), ("PageFaultCount", DWORD)] + [
        (name, SIZE_T) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
        "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class STARTUPINFO(ct.Structure):
    _fields_ = [("cb", DWORD), ("lpReserved", ct.c_wchar_p), ("lpDesktop", ct.c_wchar_p),
        ("lpTitle", ct.c_wchar_p), ("dwX", DWORD), ("dwY", DWORD), ("dwXSize", DWORD),
        ("dwYSize", DWORD), ("dwXCountChars", DWORD), ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD), ("dwFlags", DWORD), ("wShowWindow", ct.c_uint16),
        ("cbReserved2", ct.c_uint16), ("lpReserved2", ct.c_void_p),
        ("hStdInput", HANDLE), ("hStdOutput", HANDLE), ("hStdError", HANDLE)]


class PROCESS_INFORMATION(ct.Structure):
    _fields_ = [("hProcess", HANDLE), ("hThread", HANDLE), ("dwProcessId", DWORD), ("dwThreadId", DWORD)]


class BASIC_LIMIT(ct.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ct.c_int64), ("PerJobUserTimeLimit", ct.c_int64),
        ("LimitFlags", DWORD), ("MinimumWorkingSetSize", SIZE_T), ("MaximumWorkingSetSize", SIZE_T),
        ("ActiveProcessLimit", DWORD), ("Affinity", SIZE_T), ("PriorityClass", DWORD), ("SchedulingClass", DWORD)]


class IO_COUNTERS(ct.Structure):
    _fields_ = [(name, ULONG64) for name in ("ReadOperationCount", "WriteOperationCount",
        "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class EXTENDED_LIMIT(ct.Structure):
    _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", SIZE_T), ("JobMemoryLimit", SIZE_T),
        ("PeakProcessMemoryUsed", SIZE_T), ("PeakJobMemoryUsed", SIZE_T)]


class BASIC_ACCOUNTING(ct.Structure):
    _fields_ = [(name, ct.c_int64) for name in ("TotalUserTime", "TotalKernelTime",
        "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")] + [
        (name, DWORD) for name in ("TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]


class PROCESSENTRY(ct.Structure):
    _fields_ = [("dwSize", DWORD), ("cntUsage", DWORD), ("th32ProcessID", DWORD),
        ("th32DefaultHeapID", SIZE_T), ("th32ModuleID", DWORD), ("cntThreads", DWORD),
        ("th32ParentProcessID", DWORD), ("pcPriClassBase", LONG), ("dwFlags", DWORD),
        ("szExeFile", ct.c_wchar * 260)]


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def write_new(path, value):
    """One-use, atomic publish: readers never see partially written JSON."""
    path = Path(path)
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    # Hard link is atomic and fails if destination exists; no receipt replacement.
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()


def read_small(path, maximum=1048576):
    path = Path(path)
    if path.stat().st_size > maximum:
        raise ObserverError("JSON exceeds declared size bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ObserverError("JSON message must be an object")
    return value


def validate_nonce(nonce):
    if not isinstance(nonce, str) or re.fullmatch("[0-9a-f]{64}", nonce) is None:
        raise ObserverError("nonce must be 256-bit lowercase hexadecimal")


def validate_message(message, nonce, role):
    validate_nonce(nonce)
    if not isinstance(message, dict):
        raise ObserverError("message must be an object")
    if message.get("nonce") != nonce or message.get("role") != role:
        raise ObserverError("nonce or role mismatch")
    if type(message.get("pid")) is not int or message["pid"] <= 0:
        raise ObserverError("invalid process PID")
    return message


def compare_memory_bracket(before, parent, after, tolerance):
    """Return all gates, never turn mismatched process readings into a bound."""
    if type(tolerance) is not int or tolerance < 0:
        raise ObserverError("invalid comparison tolerance")
    same_identity = all(x.get("pid") == before.get("pid") and
                        x.get("creation_filetime") == before.get("creation_filetime") for x in (parent, after))
    order = before["perf_counter"] <= parent["perf_counter"] <= after["perf_counter"]
    comparisons = {}
    for name in ("resident_bytes", "private_bytes"):
        values = [x["memory"][name] for x in (before, parent, after)]
        if any(type(v) is not int or v < 0 for v in values):
            raise ObserverError("invalid memory reading")
        comparisons[name] = min(values[0], values[2]) - tolerance <= values[1] <= max(values[0], values[2]) + tolerance
    return {"same_identity": same_identity, "ordered_monotonic_bracket": order,
        "resident_within_tolerance": comparisons["resident_bytes"],
        "private_within_tolerance": comparisons["private_bytes"],
        "passed": same_identity and order and all(comparisons.values())}


def memory_limit_crossed(sample, limit):
    if type(limit) is not int or limit < 0:
        raise ObserverError("invalid private memory limit")
    return sample["memory"]["private_bytes"] > limit


class WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise UnsupportedPlatform("Windows JobObject observer unavailable; no platform fallback")
        self.k = ct.WinDLL("kernel32", use_last_error=True)
        self.p = ct.WinDLL("psapi", use_last_error=True)
        signatures = {
            "CloseHandle": ([HANDLE], BOOL), "GetCurrentProcess": ([], HANDLE),
            "GetProcessId": ([HANDLE], DWORD), "GetExitCodeProcess": ([HANDLE, ct.POINTER(DWORD)], BOOL),
            "GetProcessTimes": ([HANDLE] + [ct.POINTER(FILETIME)] * 4, BOOL),
            "OpenProcess": ([DWORD, BOOL, DWORD], HANDLE), "WaitForSingleObject": ([HANDLE, DWORD], DWORD),
            "CreateJobObjectW": ([ct.c_void_p, ct.c_wchar_p], HANDLE),
            "SetInformationJobObject": ([HANDLE, ct.c_int, ct.c_void_p, DWORD], BOOL),
            "QueryInformationJobObject": ([HANDLE, ct.c_int, ct.c_void_p, DWORD, ct.POINTER(DWORD)], BOOL),
            "AssignProcessToJobObject": ([HANDLE, HANDLE], BOOL),
            "IsProcessInJob": ([HANDLE, HANDLE, ct.POINTER(BOOL)], BOOL),
            "TerminateJobObject": ([HANDLE, ct.c_uint32], BOOL),
            "TerminateProcess": ([HANDLE, ct.c_uint32], BOOL), "ResumeThread": ([HANDLE], DWORD),
            "CreateProcessW": ([ct.c_wchar_p, ct.c_wchar_p, ct.c_void_p, ct.c_void_p, BOOL, DWORD,
                ct.c_void_p, ct.c_wchar_p, ct.POINTER(STARTUPINFO), ct.POINTER(PROCESS_INFORMATION)], BOOL),
            "CreateToolhelp32Snapshot": ([DWORD, DWORD], HANDLE),
            "Process32FirstW": ([HANDLE, ct.POINTER(PROCESSENTRY)], BOOL),
            "Process32NextW": ([HANDLE, ct.POINTER(PROCESSENTRY)], BOOL),
            "VirtualAlloc": ([ct.c_void_p, SIZE_T, DWORD, DWORD], ct.c_void_p),
            "VirtualFree": ([ct.c_void_p, SIZE_T, DWORD], BOOL)}
        for name, (args, result) in signatures.items():
            fn = getattr(self.k, name)
            fn.argtypes, fn.restype = args, result
        self.p.GetProcessMemoryInfo.argtypes = [HANDLE, ct.POINTER(MEMORY_COUNTERS), DWORD]
        self.p.GetProcessMemoryInfo.restype = BOOL

    def checked(self, value, action):
        if not value:
            raise ObserverError(action + " failed (WinError " + str(ct.get_last_error()) + ")")
        return value

    def close(self, handle):
        self.checked(self.k.CloseHandle(handle), "CloseHandle")

    def creation(self, handle):
        created, exited, kernel, user = (FILETIME() for _ in range(4))
        self.checked(self.k.GetProcessTimes(handle, ct.byref(created), ct.byref(exited),
            ct.byref(kernel), ct.byref(user)), "GetProcessTimes")
        return (created.high << 32) | created.low

    def memory(self, handle):
        m = MEMORY_COUNTERS()
        m.cb = ct.sizeof(m)
        self.checked(self.p.GetProcessMemoryInfo(handle, ct.byref(m), m.cb), "GetProcessMemoryInfo")
        return {"resident_bytes": int(m.WorkingSetSize), "private_bytes": int(m.PrivateUsage),
                "peak_resident_bytes": int(m.PeakWorkingSetSize), "backend": "Windows GetProcessMemoryInfo"}

    def self_reading(self):
        handle = self.k.GetCurrentProcess()
        return {"pid": os.getpid(), "creation_filetime": self.creation(handle),
                "memory": self.memory(handle), "perf_counter": time.perf_counter()}

    def snapshot(self):
        snap = self.k.CreateToolhelp32Snapshot(2, 0)
        if snap in (None, ct.c_void_p(-1).value):
            self.checked(False, "CreateToolhelp32Snapshot")
        entry, processes = PROCESSENTRY(), {}
        entry.dwSize = ct.sizeof(entry)
        try:
            self.checked(self.k.Process32FirstW(snap, ct.byref(entry)), "Process32FirstW")
            while True:
                processes[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not self.k.Process32NextW(snap, ct.byref(entry)):
                    error = ct.get_last_error()
                    if error != 18:  # ERROR_NO_MORE_FILES, not an ignored query failure.
                        raise ObserverError("Process32NextW failed (WinError " + str(error) + ")")
                    break
            return processes
        finally:
            self.close(snap)

    def allocate(self, count):
        if type(count) is not int or not 0 <= count <= 64 * 1024 * 1024:
            raise ObserverError("allocation exceeds fixed64MiB bound")
        if count == 0:
            return None
        pointer = self.checked(self.k.VirtualAlloc(None, count, 0x3000, 4), "VirtualAlloc")
        ct.memset(pointer, 0xA5, count)
        return pointer

    def free(self, pointer):
        if pointer:
            self.checked(self.k.VirtualFree(pointer, 0, 0x8000), "VirtualFree")


class ProcessRef:
    def __init__(self, backend, handle, expected_pid=None, expected_creation=None):
        self.backend, self.handle = backend, handle
        self.pid = int(backend.k.GetProcessId(handle))
        backend.checked(self.pid, "GetProcessId")
        self.creation_filetime = backend.creation(handle)
        if (expected_pid is not None and self.pid != expected_pid) or (
                expected_creation is not None and self.creation_filetime != expected_creation):
            raise ObserverError("retained process identity/creation mismatch")

    def alive(self):
        state = self.backend.k.WaitForSingleObject(self.handle, 0)
        if state == 0x102:
            return True
        if state == 0:
            return False
        raise ObserverError("WaitForSingleObject failed or unexpected state")

    def reading(self):
        if not self.alive():
            raise ObserverError("cannot sample exited process")
        if self.backend.creation(self.handle) != self.creation_filetime or self.backend.k.GetProcessId(self.handle) != self.pid:
            raise ObserverError("retained process identity changed")
        return {"pid": self.pid, "creation_filetime": self.creation_filetime,
                "memory": self.backend.memory(self.handle), "perf_counter": time.perf_counter()}

    def exit_code(self):
        if self.alive():
            return None
        code = DWORD()
        self.backend.checked(self.backend.k.GetExitCodeProcess(self.handle, ct.byref(code)), "GetExitCodeProcess")
        return int(code.value)

    def close(self):
        if self.handle is not None:
            self.backend.close(self.handle)
            self.handle = None


class WindowsJob:
    """One noninherited job handle; every queried process handle is retained."""
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else WindowsBackend()
        self.handle = self.backend.checked(self.backend.k.CreateJobObjectW(None, None), "CreateJobObjectW")
        self.refs = {}
        limit = EXTENDED_LIMIT()
        limit.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE only.
        try:
            self.backend.checked(self.backend.k.SetInformationJobObject(self.handle, 9,
                ct.byref(limit), ct.sizeof(limit)), "SetInformationJobObject")
        except BaseException:
            self.close()
            raise

    def start_suspended(self, command, cwd=None):
        if self.handle is None or not command or not all(isinstance(c, str) for c in command):
            raise ObserverError("invalid suspended launch")
        startup, info = STARTUPINFO(), PROCESS_INFORMATION()
        startup.cb = ct.sizeof(startup)
        line = ct.create_unicode_buffer(subprocess.list2cmdline(command))
        self.backend.checked(self.backend.k.CreateProcessW(command[0], line, None, None, False,
            0x4 | 0x08000000, None, str(cwd) if cwd is not None else None,
            ct.byref(startup), ct.byref(info)), "CreateProcessW suspended")
        assigned = False
        try:
            self.backend.checked(self.backend.k.AssignProcessToJobObject(self.handle, info.hProcess),
                "AssignProcessToJobObject before resume")
            assigned = True
            ref = ProcessRef(self.backend, info.hProcess, expected_pid=int(info.dwProcessId))
            self.refs[ref.pid] = ref
            resumed = self.backend.k.ResumeThread(info.hThread)
            if resumed != 1:
                raise ObserverError("ResumeThread did not confirm exactly one initial suspension")
            self.backend.close(info.hThread)
            return ref
        except BaseException as launch_error:
            # A suspended, unassigned launcher cannot have descendants yet.
            # Assigned failures use whole-job termination. Never resume as fallback.
            cleanup_errors = []
            try:
                if assigned:
                    self.backend.checked(self.backend.k.TerminateJobObject(self.handle, 0xE001), "TerminateJobObject after launch failure")
                else:
                    self.backend.checked(self.backend.k.TerminateProcess(info.hProcess, 0xE002), "TerminateProcess unassigned suspended launcher")
            except BaseException as error:
                cleanup_errors.append("termination: " + str(error))
            try:
                if self.backend.k.WaitForSingleObject(info.hProcess, 4000) != 0:
                    raise ObserverError("failed suspended launcher cleanup wait")
            except BaseException as error:
                cleanup_errors.append("wait: " + str(error))
            if int(info.dwProcessId) not in self.refs:
                try:
                    self.backend.close(info.hProcess)
                except BaseException as error:
                    cleanup_errors.append("process handle close: " + str(error))
            try:
                self.backend.close(info.hThread)
            except BaseException as error:
                cleanup_errors.append("thread handle close: " + str(error))
            if cleanup_errors:
                raise ObserverError("suspended launch PID " + str(int(info.dwProcessId)) + " original failure: "
                    + str(launch_error) + "; all cleanup attempted: " + "; ".join(cleanup_errors)) from launch_error
            raise

    def retain(self, pid, expected_creation=None):
        if type(pid) is not int or pid <= 0:
            raise ObserverError("invalid retained PID")
        if pid in self.refs:
            ref = self.refs[pid]
            if expected_creation is not None and ref.creation_filetime != expected_creation:
                raise ObserverError("creation mismatch for retained PID")
            return ref
        handle = self.backend.checked(self.backend.k.OpenProcess(0x100000 | 0x0400 | 0x0010, False, pid), "OpenProcess retained identity")
        try:
            ref = ProcessRef(self.backend, handle, expected_pid=pid, expected_creation=expected_creation)
        except BaseException:
            self.backend.close(handle)
            raise
        self.refs[pid] = ref
        return ref

    def member(self, ref):
        if self.handle is None:
            raise ObserverError("job membership unavailable after close")
        member = BOOL()
        self.backend.checked(self.backend.k.IsProcessInJob(ref.handle, self.handle, ct.byref(member)), "IsProcessInJob")
        if not member.value or not ref.alive():
            raise ObserverError("process is not a live member of the job")
        return True

    def authenticate(self, message, nonce, role, ancestor):
        validate_message(message, nonce, role)
        actual = self.retain(message["pid"], message["creation_filetime"])
        chain, parents = [], self.backend.snapshot()
        if parents.get(actual.pid) != message.get("parent_pid"):
            raise ObserverError("self parent PID does not match native snapshot")
        current = actual
        for _ in range(16):
            self.member(current)
            chain.append({"pid": current.pid, "creation_filetime": current.creation_filetime,
                "parent_pid": parents.get(current.pid), "job_member": True})
            if current.pid == ancestor.pid:
                return actual, chain
            parent = self.retain(parents.get(current.pid))
            if parent.creation_filetime > current.creation_filetime or any(x["pid"] == parent.pid for x in chain):
                raise ObserverError("invalid ancestry creation order/cycle")
            current = parent
        raise ObserverError("ancestry does not reach retained launcher within16levels")

    def active_count(self):
        if self.handle is None:
            raise ObserverError("job accounting unavailable after close")
        accounting = BASIC_ACCOUNTING()
        self.backend.checked(self.backend.k.QueryInformationJobObject(self.handle, 1,
            ct.byref(accounting), ct.sizeof(accounting), None), "QueryInformationJobObject accounting")
        return int(accounting.ActiveProcesses)

    def terminate(self):
        if self.handle is None:
            raise ObserverError("job already closed")
        self.backend.checked(self.backend.k.TerminateJobObject(self.handle, 0xE003), "TerminateJobObject")

    def close(self):
        if self.handle is not None:
            self.backend.close(self.handle)  # Sole handle: KILL_ON_JOB_CLOSE applies here.
            self.handle = None

    def cleanup_receipt(self, timeout, require_zero, sleep=time.sleep, clock=time.perf_counter):
        started = clock()
        deadline = started + timeout
        while True:
            exited = all(not ref.alive() for ref in self.refs.values())
            count = self.active_count() if self.handle is not None else None
            if exited and (not require_zero or count == 0):
                codes = [{"pid": ref.pid, "creation_filetime": ref.creation_filetime,
                    "exit_code": ref.exit_code()} for ref in self.refs.values()]
                completed = clock()
                if completed > deadline:
                    raise ObserverError("whole-job cleanup deadline exceeded during final queries")
                return {"all_retained_handles_exited": True, "job_active_count": count, "exit_codes": codes,
                    "started_perf_counter": started, "completed_perf_counter": completed,
                    "wall_seconds": completed - started, "timeout_seconds": timeout}
            if clock() >= deadline:
                raise ObserverError("whole-job cleanup deadline exceeded")
            sleep(0.02)

    def close_refs(self):
        errors = []
        for ref in self.refs.values():
            try:
                ref.close()
            except BaseException as error:
                errors.append(str(ref.pid) + ": " + type(error).__name__)
        if errors:
            raise ObserverError("process handle close failures (all handles attempted): " + ", ".join(errors))
