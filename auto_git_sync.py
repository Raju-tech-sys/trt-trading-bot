"""
T.R Technology — Real-Time Auto Git Sync Watcher
Monitors local project files for changes and automatically commits & pushes
to GitHub main branch, triggering Render.com instant auto-deployment.
"""
import os
import sys
import time
import subprocess
from datetime import datetime

WATCH_EXTS = {".py", ".html", ".json", ".md", ".txt", ".bat", ".sh"}
EXCLUDE_DIRS = {".git", ".venv", "__pycache__", "data_cache", "results", "browser_sandbox"}
EXCLUDE_FILES = {"live_status.json.tmp"}

GIT_BIN = r"C:\Users\FanixOP\.local\bin\git\cmd\git.exe"
if not os.path.exists(GIT_BIN):
    GIT_BIN = "git"

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_file_mtimes():
    mtimes = {}
    for root, dirs, files in os.walk(PROJECT_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f in EXCLUDE_FILES or f.startswith("."):
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext in WATCH_EXTS:
                full_path = os.path.join(root, f)
                try:
                    mtimes[full_path] = os.path.getmtime(full_path)
                except OSError:
                    pass
    return mtimes

def push_changes(changed_files):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now_str}] 🔄 Changes detected in {len(changed_files)} files. Syncing to GitHub...")
    for cf in changed_files[:3]:
        print(f"   • {os.path.basename(cf)}")
    
    try:
        env = os.environ.copy()
        git_dir = r"C:\Users\FanixOP\.local\bin\git\cmd"
        env["PATH"] = git_dir + ";" + env.get("PATH", "")

        # 1. git add
        subprocess.run([GIT_BIN, "add", "-A"], cwd=PROJECT_DIR, check=True, env=env)

        # 2. git commit
        commit_msg = f"Auto-sync update: {now_str}"
        res = subprocess.run([GIT_BIN, "commit", "-m", commit_msg], cwd=PROJECT_DIR, capture_output=True, text=True, env=env)
        if "nothing to commit" in res.stdout:
            print("   ℹ️ No net changes to commit.")
            return

        # 3. git push
        print("   🚀 Pushing to GitHub (origin/main)...")
        push_res = subprocess.run([GIT_BIN, "push", "origin", "main"], cwd=PROJECT_DIR, capture_output=True, text=True, env=env)
        if push_res.returncode == 0:
            print(f"   ✅ Pushed successfully! Render.com is now auto-deploying live.")
        else:
            print(f"   ⚠️ Push output: {push_res.stderr.strip() or push_res.stdout.strip()}")
    except Exception as e:
        print(f"   🛑 Sync error: {e}")

def main():
    print("=" * 70)
    print("  TRT PRO TRADER — REAL-TIME AUTO GIT SYNC WATCHER")
    print("  Auto-detects file changes and pushes to GitHub -> Render Live")
    print("=" * 70)
    print(f"  Watching: {PROJECT_DIR}")
    print("  Press Ctrl+C to stop.\n")

    last_mtimes = get_file_mtimes()

    while True:
        try:
            time.sleep(3)
            current_mtimes = get_file_mtimes()
            changed = []

            for path, mtime in current_mtimes.items():
                if path not in last_mtimes or mtime > last_mtimes[path]:
                    changed.append(path)

            if changed:
                time.sleep(2)  # Wait for file write to settle
                push_changes(changed)
                last_mtimes = get_file_mtimes()

        except KeyboardInterrupt:
            print("\nAuto-sync watcher stopped.")
            break
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    main()
