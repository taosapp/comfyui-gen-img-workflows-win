"""Determine whether this GPU actually has the GeForce half-rate FP32-accumulate limit.

torch.matmul always uses FP32 accumulation for fp16 inputs, so comparing
torch fp16 against torch bf16 proves nothing. This probes cuBLAS directly and
selects the accumulation type explicitly:

  CUBLAS_COMPUTE_16F  -> FP16 inputs, FP16 accumulate   (not rate limited)
  CUBLAS_COMPUTE_32F  -> FP16 inputs, FP32 accumulate   (rate limited on GeForce)

If the FP16-accumulate path runs at ~2x the FP32-accumulate path, the card
carries the limit that gpu-unlock removes. If both land on the same number,
the card is not limited in this way and the unlock would buy nothing.
"""

import ctypes
import os
import sys
import time

import torch

DEV = "cuda:0"
N = 4096

CUBLAS_COMPUTE_16F = 64
CUBLAS_COMPUTE_32F = 68
CUBLAS_COMPUTE_32F_FAST_16BF = 75

CUDA_R_16F = 2
CUDA_R_16BF = 7
CUBLAS_OP_N = 0
CUBLAS_GEMM_DEFAULT = -1
CUBLAS_GEMM_DEFAULT_TENSOR_OP = 99


def load_cublas():
    libdir = os.path.join(os.path.dirname(torch.__file__), "lib")
    os.add_dll_directory(libdir)

    import glob
    candidates = glob.glob(os.path.join(libdir, "cublas64_*.dll"))
    if not candidates:
        candidates = glob.glob(
            os.path.join(sys.prefix, "Library", "bin", "cublas64_*.dll"))
    if not candidates:
        raise RuntimeError("cublas dll not found")

    lib = ctypes.CDLL(candidates[0])
    lib.cublasCreate_v2.restype = ctypes.c_int
    lib.cublasSetMathMode.restype = ctypes.c_int
    lib.cublasGemmEx.restype = ctypes.c_int
    lib.cublasGemmEx.argtypes = [
        ctypes.c_void_p,                      # handle
        ctypes.c_int, ctypes.c_int,           # transa, transb
        ctypes.c_int, ctypes.c_int, ctypes.c_int,   # m, n, k
        ctypes.c_void_p,                      # alpha
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,   # A, Atype, lda
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,   # B, Btype, ldb
        ctypes.c_void_p,                      # beta
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int,   # C, Ctype, ldc
        ctypes.c_int,                         # computeType
        ctypes.c_int,                         # algo
    ]
    handle = ctypes.c_void_p()
    if lib.cublasCreate_v2(ctypes.byref(handle)) != 0:
        raise RuntimeError("cublasCreate failed")
    lib.cublasSetMathMode(handle, 0)  # CUBLAS_DEFAULT_MATH
    return lib, handle


def gemm_ex(lib, handle, a, b, c, compute_type, algo=CUBLAS_GEMM_DEFAULT):
    alpha = ctypes.c_void_p(ctypes.addressof(ctypes.c_float(1.0)))
    beta = ctypes.c_void_p(ctypes.addressof(ctypes.c_float(0.0)))
    status = lib.cublasGemmEx(
        handle, CUBLAS_OP_N, CUBLAS_OP_N,
        ctypes.c_int(a.shape[0]), ctypes.c_int(b.shape[1]), ctypes.c_int(a.shape[1]),
        alpha,
        ctypes.c_void_p(a.data_ptr()), ctypes.c_int(CUDA_R_16F), ctypes.c_int(a.stride(0)),
        ctypes.c_void_p(b.data_ptr()), ctypes.c_int(CUDA_R_16F), ctypes.c_int(b.stride(0)),
        beta,
        ctypes.c_void_p(c.data_ptr()), ctypes.c_int(CUDA_R_16F), ctypes.c_int(c.stride(0)),
        ctypes.c_int(compute_type), ctypes.c_int(algo),
    )
    if status != 0:
        raise RuntimeError(f"cublasGemmEx status={status}")


def bench(lib, handle, dtype, compute_type, algo, reps=30):
    a = torch.randn(N, N, device=DEV, dtype=dtype)
    b = torch.randn(N, N, device=DEV, dtype=dtype)
    c = torch.empty(N, N, device=DEV, dtype=dtype)

    for _ in range(5):
        gemm_ex(lib, handle, a, b, c, compute_type, algo)
    torch.cuda.synchronize()

    best = 0.0
    for _ in range(3):
        t0 = time.perf_counter()
        for _ in range(reps):
            gemm_ex(lib, handle, a, b, c, compute_type, algo)
        torch.cuda.synchronize()
        dt = (time.perf_counter() - t0) / reps
        best = max(best, (2 * N**3) / dt / 1e12)
    return best


def main():
    props = torch.cuda.get_device_properties(0)
    print(f"GPU: {props.name}  SMs={props.multi_processor_count}  "
          f"sm_{props.major}{props.minor}  {props.total_memory / 1024**3:.0f} GiB")
    print(f"matrix: {N}^3, cuBLAS {torch.version.cuda}, torch {torch.__version__}\n")

    lib, handle = load_cublas()

    cases = [
        ("FP16 acc   COMPUTE_16F", torch.float16, CUBLAS_COMPUTE_16F, CUBLAS_GEMM_DEFAULT),
        ("FP16 acc   COMPUTE_16F/T", torch.float16, CUBLAS_COMPUTE_16F, CUBLAS_GEMM_DEFAULT_TENSOR_OP),
        ("FP32 acc   COMPUTE_32F", torch.float16, CUBLAS_COMPUTE_32F, CUBLAS_GEMM_DEFAULT),
        ("FP32 acc   COMPUTE_32F/T", torch.float16, CUBLAS_COMPUTE_32F, CUBLAS_GEMM_DEFAULT_TENSOR_OP),
    ]

    res = {}
    for label, dt, ct, algo in cases:
        try:
            t = bench(lib, handle, dt, ct, algo)
            res[label] = t
            print(f"{label:28s} {t:7.2f} TFLOPS")
        except RuntimeError as e:
            print(f"{label:28s} FAILED: {e}")

    print()
    f16 = max((v for k, v in res.items() if k.startswith("FP16 acc")), default=None)
    f32 = max((v for k, v in res.items() if k.startswith("FP32 acc")), default=None)
    if f16 and f32:
        ratio = f16 / f32
        print(f"best FP16-accumulate = {f16:.2f} TFLOPS")
        print(f"best FP32-accumulate = {f32:.2f} TFLOPS")
        print(f"ratio = {ratio:.3f}")
        if ratio > 1.5:
            print(">>> card IS half-rate limited on the FP32-accumulate path")
            print(f">>> unlock would be expected to lift that path toward {f16:.0f} TFLOPS")
        else:
            print(">>> no half-rate asymmetry: unlock would buy ~0 on this path")

    import subprocess
    print()
    print(subprocess.run(
        ["nvidia-smi", "--query-gpu=power.draw,power.limit,clocks.sm,"
         "clocks.max.sm,temperature.gpu,utilization.gpu", "--format=csv"],
        capture_output=True, text=True).stdout)


if __name__ == "__main__":
    main()
