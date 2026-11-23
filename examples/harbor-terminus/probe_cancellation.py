"""Exercise the public run_tasks API in an event loop that remains alive."""

import asyncio
import json
import sys


async def main(mode):
    # The sealed submission is mounted read-only in the offline task container.
    sys.path.insert(0, "/submission")
    from run import run_tasks

    loop = asyncio.get_running_loop()
    if mode == "future":
        invoked = []

        def factory():
            invoked.append(1)
            ready = loop.create_future()
            ready.set_result(None)
            return ready

        await run_tasks([factory] * 3, 2)
        return {"factories_invoked": len(invoked)}

    started, cleaned, interrupted = [], [], []
    two_started = asyncio.Event()

    async def job(i):
        started.append(i)
        if len(started) == 2:
            two_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            try:
                await asyncio.sleep(0.03)
                cleaned.append(i)
            except asyncio.CancelledError:
                interrupted.append([i, asyncio.current_task().cancelling()])
                raise

    runner = asyncio.create_task(run_tasks([lambda i=i: job(i) for i in range(4)], 2))
    await asyncio.wait_for(two_started.wait(), 1)
    runner.cancel()
    try:
        await runner
        exit_kind = "returned"
    except asyncio.CancelledError:
        exit_kind = "cancelled"
    return {
        "caller_observed": exit_kind,
        "started": sorted(started),
        "cleaned_by_caller_resumption": sorted(cleaned),
        "interrupted_cleanup_and_cancel_counts": sorted(interrupted),
        "other_pending_tasks": len(asyncio.all_tasks() - {asyncio.current_task()}),
    }


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(main(sys.argv[1]))))
    except Exception as error:
        print(json.dumps({"error_type": type(error).__name__}))
