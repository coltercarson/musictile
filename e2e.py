"""Browser test of the whole flow on an emulated Pixel, using the Local file source (no credentials).

Run on the host against the running container:  python3 e2e.py [http://localhost:5050]
Needs `pip install playwright && playwright install chromium`, and ffmpeg.
Checks both Save paths: the share sheet (navigator.share stubbed, as on HTTPS or with the Chrome flag)
and the download fallback (plain HTTP). Android rules that desktop Chrome doesn't enforce are asserted
explicitly: share needs a live tap, and only one download per tap gets through.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5050"
N = 3  # Save all only shows for 2+ clips

# Record what Save hands to the share sheet, and whether the tap still counted as a user gesture.
SHARE_STUB = """
window.__shared = [];
navigator.canShare = (d) => !!(d && d.files && d.files.length);
navigator.share = async (d) => {
  if (!navigator.userActivation.isActive) throw new DOMException('Must be handling a user gesture', 'NotAllowedError');
  window.__shared.push(d.files.map((f) => [f.name, f.type, f.size]));
};
"""


def tones(dir: Path):
    files = []
    for i in range(N):
        f = dir / f"tone {i}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine={300 + 100 * i}:d=12",
                        "-f", "lavfi", "-i", "color=c=teal:s=400x300:d=1", "-frames:v", "1",
                        "-map", "0:a", "-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic", str(f)],
                       check=True)  # embedded cover art, like a real tagged file
        files.append(f)
    return files


def run(p, files, share: bool):
    ctx = p.chromium.launch().new_context(**p.devices["Pixel 7"], accept_downloads=True)
    if share:
        ctx.add_init_script(SHARE_STUB)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    downloads = []
    page.on("download", lambda d: downloads.append(d))

    page.goto(BASE)
    page.evaluate("localStorage.clear()")
    page.reload()
    page.get_by_role("button", name="Local file").click()
    page.locator("input[type=file][accept='audio/*']").set_input_files([str(f) for f in files])
    page.locator("nav.steps button[data-step=export]").click()
    render = page.get_by_role("button", name=f"Render {N} clips")
    expect(render).to_be_enabled(timeout=60_000)
    render.click()
    saves = page.get_by_role("button", name="Save", exact=True)
    expect(saves).to_have_count(N, timeout=120_000)
    if share:
        save_all = page.get_by_role("button", name=f"Save all {N}")
        expect(save_all).to_be_enabled(timeout=30_000)
        save_all.click()
        page.wait_for_timeout(1000)
        shared = page.evaluate("window.__shared")
        assert len(shared) == 1 and len(shared[0]) == N, f"share got {shared}"
        assert all(t == "video/mp4" and size > 10_000 for _, t, size in shared[0]), shared
    else:
        expect(page.get_by_role("button", name=f"Save all {N}")).to_have_count(0)
        for i in range(N):  # one tap, one download
            expect(saves.nth(i)).to_be_enabled(timeout=30_000)
            with page.expect_download() as dl:
                saves.nth(i).click()
            page.wait_for_timeout(1000)
            assert len(downloads) == i + 1, f"tap {i + 1} started {len(downloads) - i} downloads"
            assert dl.value.suggested_filename.endswith(".mp4")
    assert not errors, errors
    ctx.browser.close()
    print(f"OK  {'Save all via share sheet' if share else 'Save per clip via downloads'}")


with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
    files = tones(Path(tmp))
    run(p, files, share=True)
    run(p, files, share=False)
