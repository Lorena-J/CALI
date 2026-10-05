# Mini2P / Behavior Synchronization Viewer

## Install

Open PowerShell in this folder:

```powershell
py -m pip install -r requirements.txt
```

## Run

```powershell
py sync_viewer.py
```

Load, in any order:

1. Camera TTL CSV
2. Mini2P TTL CSV
3. Behavior MP4
4. ScanImage TIFF

The common timeline uses the Arduino clock, with `t = 0` at the first Mini2P TTL.

## Controls

- Click or drag the vertical cursor on the timeline.
- Mouse wheel: zoom timeline.
- Hover over TTL marks: frame, timestamp, nearest frame of the other device and delta.
- Left/Right: previous/next Mini2P frame.
- Page Up/Page Down or the buttons: previous/next camera STROBE gap.
- Red X marks are suspicious camera STROBE intervals (>1.5x median period).

## Camera → MP4 mapping

Two modes are available:

- **TTL index**: STROBE #N maps to MP4 frame #N (+ optional start offset).
- **Timing reconstruction**: a ~2x STROBE interval advances the virtual MP4 index by 2, a ~3x interval by 3, etc.

Timing reconstruction is useful for QC but is an assumption: it treats a missing STROBE observation as if the corresponding video exposure/frame still existed. It is not proof that the exposure occurred.

`MP4 start offset = 0` means the first camera STROBE maps to MP4 frame 1.
