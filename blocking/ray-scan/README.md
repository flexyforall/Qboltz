# ray-scan: blocking

Greybox previz for the Seedance pass. One continuous 15 s shot on a checkerboard void.

| time | beat |
|---|---|
| 0.0 | wide, slightly in front of and above the hub; six rays thrash, scanning |
| 2.6 | the camera drifts round; the rays sweep past |
| 4.5 | close on YELLOW, which calms as the camera holds on it |
| 5.2 | YELLOW swings away; the camera eases back and pans across to MAGENTA |
| 8.5 | close on MAGENTA; it calms and locks |
| 9.3 | slip onto MAGENTA's line, just above it |
| 12.5 | follow MAGENTA as its tip stretches away into the distance |

Open `ray_scan.blend` and press Space. It opens in camera view with solid shading on frame 1.

## Files

- `rays.py`: the ray motion. It is shared by the spec and the build, so the camera and the rays never disagree.
- `ray_scan.py`: the shot spec for the seedance-blocking solver. The subject is a hidden attention proxy that rides wherever the camera should look.
- `bake.json`: the solved camera, written by the solver.
- `check_rays.py`: checks that no ray sweeps through the lens. The solver only gates the camera against the proxy.
- `build.py`: builds `ray_scan.blend` from the bake.

## Rebuild after a change

```sh
python3 <skill>/scripts/solve_shot.py ray_scan.py   # gimbal gates; must exit 0
python3 check_rays.py                               # ray clearance; must exit 0
blender -b -P build.py                              # -> ray_scan.blend
```
