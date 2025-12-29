# Streamlit output folder setup (set once, reuse everywhere)

This short guide shows how to **set the output folder one time** before you launch Streamlit. When you do this, every dashboard page will already know where your saved results live—so you do **not** have to retype the output path on each page. You can set it either in the **Configuration** page inside Streamlit or by pre-filling the value before launch.

## Why this helps (plain language)
- **Less repeated typing:** you set the folder once, and every page reads from it automatically.
- **Fewer mistakes:** everyone sees the same saved outputs, which keeps reviews consistent.
- **Local-only:** the path is only used on your computer—nothing is uploaded anywhere.

## Option A: Set it in Streamlit (recommended for most users)
1. Launch the dashboards:
   ```bash
   streamlit run analysis/streamlit/Home.py
   ```
2. Open the **Configuration** page from the left navigation.
3. Enter your output folder and click **Save configuration**.

All other pages will now use the same folder automatically.

## Option B: Set an environment variable
Set `DOJ_OUTPUT_DIR` to the folder that contains your `inventory/`, `probes/`, and `labels/` outputs.

### macOS / Linux (Terminal)
```bash
export DOJ_OUTPUT_DIR="/full/path/to/outputs"
streamlit run analysis/streamlit/Home.py
```

### Windows (PowerShell)
```powershell
$env:DOJ_OUTPUT_DIR = "C:\full\path\to\outputs"
streamlit run analysis/streamlit/Home.py
```

> **Tip:** Add the export line to your shell profile (like `~/.zshrc` or `~/.bashrc`) if you want it to persist between sessions.

## Option C: Pass the output folder as a launch argument
If you prefer not to use environment variables, you can pass the folder once when you start Streamlit:

```bash
streamlit run analysis/streamlit/Home.py -- --out /full/path/to/outputs
```

This `--out` value is picked up by all pages on launch, so the default is already filled in.

## How to confirm it worked
When you open a dashboard page (Inventory QA, Probe QA, Document Filter, etc.), the **Output folder** field should already show your chosen path. If it does, you are done.

## If you need to switch folders later
Just update the path on the **Configuration** page, or update the environment variable and relaunch Streamlit.
