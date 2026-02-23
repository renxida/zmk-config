# ZMK Config

Cradio (Sweep), nice!nano v2, BLE, Colemak-DH, 34 keys.
Branch: `cradio-rebased-2025`.

## Key Naming
- Refer to positions by **Colemak-DH letter** (e.g. "H position"), never ZMK codes like RM3
- Thumbs: **left/right inner/outer** (e.g. "right inner thumb")
- Always think in Colemak-DH, never QWERTY
- "chord" = ZMK combo in user vocabulary

## Design Constraints
- 34 keys — never suggest keycodes that don't exist on the board
- Right inner thumb = SMART_NUM — must stay available on all layers (Regolith workspace switching)
- Mouse layer: left hand transparent (homerow mods pass through for drag ops)
- F13 (P+W combo) and F14 (L+Y combo) reserved for OS integration

## Working With the Config
- **Always read the actual keymap/combos files before answering** — no generic ZMK answers
- Check combos file before suggesting new layer bindings (may already exist)
- Check for positional conflicts when adding combos/keys
- Prefer OS-level hotkey changes over firmware changes when possible

## Build & Flash
- CI: GitHub Actions via `renxida/zmk-actions` (fork of urob, stamps commit hash into BLE name "SS-<hash>")
- **Firmware comes from CI, not local builds** — push -> wait for CI -> download artifact -> flash
- Artifact pattern: `artifact-{board}_{side}-{controller}-zmk`
- Bootloader mounts at `/media/cedar/NICENANO` — watch with bg loop, copy UF2
- User can't type during flash; act autonomously after they indicate reset
- Leader combo S+T then B-O-O-T enters bootloader; physical double-tap reset also works
