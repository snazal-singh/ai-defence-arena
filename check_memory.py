import subprocess
import re
import os

def check_mac_memory():
    print("==================================================")
    print("       🧠 MACBOOK SYSTEM MEMORY DIAGNOSTIC        ")
    print("==================================================")

    # 1. Try to use psutil if available
    try:
        import psutil
        vm = psutil.virtual_memory()
        total_gb = vm.total / (1024**3)
        available_gb = vm.available / (1024**3)
        used_percent = vm.percent
        method = "psutil library"
    except ImportError:
        # Fallback: Native macOS command line parsers (No installation needed)
        method = "macOS native commands (sysctl & vm_stat)"
        try:
            # Get total physical memory in bytes
            total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip())
            total_gb = total_bytes / (1024**3)

            # Get Virtual Memory stats
            vm_info = subprocess.check_output(["vm_stat"]).decode("utf-8")
            
            # Default macOS page size is 4096 bytes
            page_size = 4096
            page_size_match = re.search(r"page size of (\d+) bytes", vm_info)
            if page_size_match:
                page_size = int(page_size_match.group(1))

            # Extract memory page counts
            stats = {}
            for line in vm_info.split("\n"):
                if ":" in line and not line.startswith("Mach Virtual Memory"):
                    key, val = line.split(":")
                    clean_val = val.strip().replace(".", "")
                    if clean_val.isdigit():
                        stats[key.strip()] = int(clean_val)

            # macOS Available Memory = Free + Inactive + Speculative + Purgeable
            free_pages = stats.get("Pages free", 0)
            inactive_pages = stats.get("Pages inactive", 0)
            speculative_pages = stats.get("Pages speculative", 0)
            purgeable_pages = stats.get("Pages purgeable", 0)

            available_bytes = (free_pages + inactive_pages + speculative_pages + purgeable_pages) * page_size
            available_gb = available_bytes / (1024**3)
            used_percent = ((total_gb - available_gb) / total_gb) * 100
        except Exception as e:
            print(f"❌ Failed to parse native system memory metrics: {e}")
            return

    # Print diagnostics
    print(f"Diagnostic Method: {method}")
    print(f"Total Physical RAM: {total_gb:.2f} GB")
    print(f"Available/Free RAM: {available_gb:.2f} GB")
    print(f"Used Memory Ratio:  {used_percent:.1f}%")
    print("--------------------------------------------------")

    # 2. Evaluate feasibility of loading the Conformer model (requires ~2.5 - 3.0 GB)
    print("📋 FEASIBILITY ASSESSMENT FOR INDIC-CONFORMER:")
    if available_gb >= 3.5:
        print("🟢 SAFE TO RUN!")
        print("   You have plenty of free memory. The model (approx. 2.5GB) will load")
        print("   and run smoothly without lagging your MacBook.")
    elif 2.0 <= available_gb < 3.5:
        print("🟡 BORDERLINE (MEM LIMIT CLOSE)")
        print("   You have enough memory to run the model, but it will consume most")
        print("   of your remaining free RAM. Close unneeded heavy apps (like Chrome")
        print("   tabs or Docker) before loading it to avoid minor lag.")
    else:
        print("🔴 HIGH RISK OF SLUGGISHNESS")
        print(f"   You only have {available_gb:.2f} GB of free RAM. Loading a 2.5GB model")
        print("   will force macOS into active memory-swapping (using your SSD as RAM).")
        print("   It will still run, but your system and transcription speeds will be slow.")
    print("==================================================")

if __name__ == "__main__":
    check_mac_memory()
