Apply the patch from the benchmark repo root:

```bash
git apply /Users/batuhanaktas/Development/prod/kai-agent-new/patches/nvidia-kernel-benchmark-cublas.patch
```

Validation on a CUDA machine:

```bash
python run_benchmarks.py --mode basic
```

What to check after apply:

- `backend_details["dispatch_verification"]["verified"]` is `True` for the cuBLAS run.
- `backend_details["preferred_blas_library"]` reports the configured BLAS backend.
- `disable_tf32` is `True` unless you intentionally relax it.
- `gpu_utilization` and `backend_details["gpu_util_samples"]` are non-zero under load when NVML is available.
- GEMV uses `torch.addmv` or `torch.ops.aten.addmv.default`.
- GEMM uses `torch.baddbmm` or `torch.addmm` in `loop_addmm` mode.
