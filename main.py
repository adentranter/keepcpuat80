#!/usr/bin/env python3



import os
import time
import shutil
import psutil
import multiprocessing as mp





TARGET_CPU = float(os.getenv("TARGET_CPU", "80.0"))



# How often the controller reacts.
# Lower = faster reaction, but more noisy.
CONTROL_INTERVAL = float(os.getenv("CONTROL_INTERVAL", "0.10"))



# How often the terminal line updates.
DISPLAY_INTERVAL = float(os.getenv("DISPLAY_INTERVAL", "0.50"))



# Number of worker processes.
# Usually os.cpu_count() is fine.
WORKER_COUNT = int(os.getenv("WORKER_COUNT", str(os.cpu_count() or 1)))



# Starting math workload size per chunk.
START_MATH_LOOPS = int(os.getenv("MATH_LOOPS", "1000"))



# Limits for auto-tuning.
MIN_MATH_LOOPS = int(os.getenv("MIN_MATH_LOOPS", "10"))
MAX_MATH_LOOPS = int(os.getenv("MAX_MATH_LOOPS", "100000"))



# How quickly math_loops changes.
# Smaller = smoother.
# Bigger = more aggressive.
TUNE_STEP = float(os.getenv("TUNE_STEP", "0.05"))



# Prevents immediate bounce back after going over target.
# Example: target 80, resume 77 means:
# - if CPU >= 80, stop math
# - only resume once CPU is below 77
RESUME_CPU = float(os.getenv("RESUME_CPU", str(TARGET_CPU - 3.0)))





def clear_line_and_print(text: str):
    width = shutil.get_terminal_size((180, 20)).columns
    print("\r" + text.ljust(width), end="", flush=True)





def perform_math(math_loops: int):
    """
    Simple repeated math workload.



    The actual math is intentionally boring.
    The point is to create measurable CPU work.
    """
    x = 0



    for _ in range(math_loops):
        x += 10 * 2



    return x





def worker_loop(worker_id: int, active_workers, math_loops, stop_event):
    """
    Worker process.



    If worker_id is below active_workers.value, it performs math.
    Otherwise, it sleeps.
    """
    while not stop_event.is_set():
        if worker_id < active_workers.value:
            perform_math(math_loops.value)
        else:
            time.sleep(0.02)





def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))





def calculate_wanted_workers(current_cpu: float) -> int:
    """
    Estimate how many workers we need based on the CPU gap.



    Rough idea:
    if there are 12 workers, each fully active worker is roughly 8.3%
    of total CPU.
    """
    if current_cpu >= TARGET_CPU:
        return 0



    gap = TARGET_CPU - current_cpu
    cpu_per_worker = 100.0 / max(WORKER_COUNT, 1)



    wanted_workers = round(gap / cpu_per_worker)



    # If we are below target, allow at least 1 worker.
    wanted_workers = max(1, int(wanted_workers))



    return clamp_int(wanted_workers, 0, WORKER_COUNT)





def main():
    print(f"CPU logical cores:    {os.cpu_count()}")
    print(f"Worker processes:     {WORKER_COUNT}")
    print(f"Target CPU:           {TARGET_CPU:.1f}%")
    print(f"Resume CPU:           {RESUME_CPU:.1f}%")
    print(f"Control interval:     {CONTROL_INTERVAL:.3f}s")
    print(f"Display interval:     {DISPLAY_INTERVAL:.3f}s")
    print(f"Start math loops:     {START_MATH_LOOPS:,}")
    print(f"Min math loops:       {MIN_MATH_LOOPS:,}")
    print(f"Max math loops:       {MAX_MATH_LOOPS:,}")
    print(f"Tune step:            {TUNE_STEP:.3f}")
    print("Press Ctrl+C to stop.")
    print()



    active_workers = mp.Value("i", 0)
    math_loops = mp.Value("i", START_MATH_LOOPS)
    stop_event = mp.Event()



    workers = []



    for worker_id in range(WORKER_COUNT):
        process = mp.Process(
            target=worker_loop,
            args=(worker_id, active_workers, math_loops, stop_event),
            daemon=True,
        )
        process.start()
        workers.append(process)



    # Prime psutil.
    psutil.cpu_percent(interval=None)



    last_cpu = 0.0
    last_display = time.perf_counter()
    cooling_down = False
    action = "STARTING"



    try:
        while True:
            time.sleep(CONTROL_INTERVAL)



            current_cpu = psutil.cpu_percent(interval=None)



            if current_cpu >= TARGET_CPU:
                # Hard cutoff: no random math.
                active_workers.value = 0
                cooling_down = True
                action = "NO MATH"



                # Back the chunk size down slightly while over target.
                math_loops.value = clamp_int(
                    int(math_loops.value * (1.0 - TUNE_STEP)),
                    MIN_MATH_LOOPS,
                    MAX_MATH_LOOPS,
                )



            elif cooling_down and current_cpu > RESUME_CPU:
                # Still close to target, so keep math off.
                active_workers.value = 0
                action = "COOLDOWN"



            else:
                # Below target enough to resume.
                cooling_down = False



                wanted_workers = calculate_wanted_workers(current_cpu)
                active_workers.value = wanted_workers



                # Tune chunk size based on whether CPU seems to be rising.
                #
                # If CPU is not moving up much, increase workload.
                # If CPU has jumped upward, reduce workload.
                if current_cpu <= last_cpu + 0.5:
                    new_loops = int(math_loops.value * (1.0 + TUNE_STEP))
                else:
                    new_loops = int(math_loops.value * (1.0 - TUNE_STEP))



                math_loops.value = clamp_int(
                    new_loops,
                    MIN_MATH_LOOPS,
                    MAX_MATH_LOOPS,
                )



                action = "MATH"



            now = time.perf_counter()



            if now - last_display >= DISPLAY_INTERVAL:
                clear_line_and_print(
                    f"CPU: {current_cpu:5.1f}% | "
                    f"Target: {TARGET_CPU:5.1f}% | "
                    f"Resume: {RESUME_CPU:5.1f}% | "
                    f"Action: {action:<8} | "
                    f"Workers: {active_workers.value:2d}/{WORKER_COUNT:<2d} | "
                    f"Loops/chunk: {math_loops.value:>8,} | "
                    f"Control: {CONTROL_INTERVAL:.3f}s"
                )



                last_display = now



            last_cpu = current_cpu



    except KeyboardInterrupt:
        pass



    finally:
        active_workers.value = 0
        stop_event.set()



        for process in workers:
            process.join(timeout=1)



        print("\nStopped.")





if __name__ == "__main__":
    main()