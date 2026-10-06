import subprocess
import sys
from pathlib import Path

from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_generated_modules_and_typing_stubs_exist() -> None:
    assert motor_pb2.DESCRIPTOR.package == "hiyelx.v1"
    assert motor_pb2_grpc.MotorServiceStub is not None
    generated = PROJECT_ROOT / "src/hiyelx/rpc/generated"
    assert (generated / "motor_pb2.pyi").is_file()
    assert (generated / "motor_pb2_grpc.pyi").is_file()


def test_service_descriptor_is_versioned() -> None:
    service = motor_pb2.DESCRIPTOR.services_by_name["MotorService"]
    assert service.full_name == "hiyelx.v1.MotorService"
    assert tuple(method.name for method in service.methods) == (
        "ListMotors",
        "GetMotorState",
        "ApplyMotorCommand",
        "StopMotor",
    )


def test_generated_output_is_current() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/generate_proto.py", "--check"],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
