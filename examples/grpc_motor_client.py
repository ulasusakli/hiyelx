"""Minimal asynchronous client for a local HIYELX MotorService."""

import asyncio

import grpc

from hiyelx.rpc.generated import motor_pb2, motor_pb2_grpc


async def main() -> None:
    channel = grpc.aio.insecure_channel("127.0.0.1:50051")
    try:
        client = motor_pb2_grpc.MotorServiceStub(channel)
        listing = await client.ListMotors(motor_pb2.ListMotorsRequest())
        for motor in listing.motors:
            print(motor.identity)

        identity = listing.motors[0].identity
        await client.ApplyMotorCommand(
            motor_pb2.ApplyMotorCommandRequest(
                identity=identity,
                angular_velocity_radians_per_second=1.0,
            )
        )
        state = await client.GetMotorState(motor_pb2.GetMotorStateRequest(identity=identity))
        print(state.state)
        await client.StopMotor(motor_pb2.StopMotorRequest(identity=identity))
    finally:
        await channel.close()


if __name__ == "__main__":
    asyncio.run(main())
