import sys, traceback
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

print("Step 1: importing fotnssj...", flush=True)
try:
    import fotnssj
    print("Step 2: import OK", flush=True)
    fotnssj.seed_demo_data()
    print("Step 3: seed OK, starting Flask on port 5000...", flush=True)
    fotnssj.app.run(debug=False, host="127.0.0.1", port=5000)
except Exception as e:
    print(f"FATAL: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
