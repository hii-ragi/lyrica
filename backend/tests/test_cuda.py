import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from lyrica_backend.device import cuda_settings, friendly_error
from lyrica_backend.runtime import (
    fingerprint, python_path, run_worker, runtime_env, runtime_status, setup_runtime, validate_device,
)


class CudaSettingsTests(unittest.TestCase):
    def test_only_cpu_and_nvidia_cuda_are_supported(self):
        for device in ("cpu","cuda"):
            self.assertEqual(validate_device(device),device)
        for device in ("rocm","mps","directml",None):
            with self.subTest(device=device),self.assertRaises(ValueError):
                validate_device(device)

    def test_low_memory_defaults_and_explicit_choices(self):
        self.assertEqual(cuda_settings({}),("int8_float16",15))
        self.assertEqual(cuda_settings({"cuda_compute_type":"float16","cuda_max_segment_seconds":10}),("float16",10))
        for value in (0,30,True,float("nan"),"15"):
            with self.subTest(value=value),self.assertRaises(ValueError):
                cuda_settings({"cuda_max_segment_seconds":value})

    def test_errors_explain_memory_or_dll_failure(self):
        self.assertIn("メモリ",friendly_error(RuntimeError("CUDA out of memory")))
        self.assertIn("再準備",friendly_error(RuntimeError("Library cublas64_12.dll is not found")))
        self.assertEqual(friendly_error(ValueError("regular error")),"regular error")


class CudaRuntimeTests(unittest.TestCase):
    def test_separate_interpreters_and_cuda_dll_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertNotEqual(python_path(folder),python_path(folder,"cuda"))
            self.assertIn("venv-cuda",str(python_path(folder,"cuda")))
            cpu,cuda = runtime_env(folder,folder),runtime_env(folder,folder,"cuda")
            self.assertEqual(cpu["LYRICA_DEVICE"],"cpu")
            self.assertEqual(cuda["LYRICA_DEVICE"],"cuda")
            self.assertEqual(cpu["HF_HOME"],cuda["HF_HOME"])
            self.assertIn("venv-cuda",cuda["PATH"])

    def test_cuda_requirements_do_not_invalidate_cpu_install(self):
        with tempfile.TemporaryDirectory() as folder:
            home,resources = Path(folder)/"runtime",Path(folder)/"resources"
            home.mkdir();resources.mkdir()
            for name in ("requirements-analysis.txt","constraints-analysis.txt",
                         "requirements-analysis-cuda.txt","constraints-analysis-cuda.txt"):
                (resources/name).write_text(name)
            for device,marker in (("cpu","ready.txt"),("cuda","ready-cuda.txt")):
                python_path(home,device).parent.mkdir(parents=True)
                python_path(home,device).touch()
                (home/marker).write_text(fingerprint(resources,device))
            with patch("lyrica_backend.runtime.probe_nvidia",return_value={"available":True,"name":"GPU"}):
                self.assertTrue(runtime_status(home,resources)["ready"])
                self.assertTrue(runtime_status(home,resources,"cuda")["ready"])
                (resources/"constraints-analysis-cuda.txt").write_text("new CUDA dependency")
                self.assertTrue(runtime_status(home,resources)["ready"])
                self.assertFalse(runtime_status(home,resources,"cuda")["ready"])
            with patch("lyrica_backend.runtime.probe_nvidia",return_value={"available":False}):
                self.assertTrue(runtime_status(home,resources)["ready"])
                self.assertFalse(runtime_status(home,resources,"cuda")["ready"])

    def test_no_gpu_fails_before_downloading(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("lyrica_backend.runtime.probe_nvidia",return_value={"available":False}), \
                 patch("lyrica_backend.runtime.subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError,"NVIDIA"):
                    setup_runtime(Path(folder)/"new",folder,"uv",lambda *args:None,"cuda")
                run.assert_not_called()
                self.assertFalse((Path(folder)/"new").exists())

    def test_cuda_request_is_routed_to_cuda_python(self):
        with tempfile.TemporaryDirectory() as folder:
            request={"operation":"analyze","options":{"device":"cuda"}}
            result=subprocess.CompletedProcess([],0,stdout=json.dumps({"device":"cuda"}))
            with patch("lyrica_backend.runtime.runtime_status",return_value={"ready":True}), \
                 patch("lyrica_backend.runtime.subprocess.run",return_value=result) as run:
                self.assertEqual(run_worker(request,folder,folder),{"device":"cuda"})
                self.assertEqual(run.call_args.args[0][0],str(python_path(folder,"cuda")))
                self.assertEqual(run.call_args.kwargs["env"]["LYRICA_DEVICE"],"cuda")
                self.assertEqual(json.loads(run.call_args.kwargs["input"]),request)


if __name__ == "__main__":
    unittest.main()
