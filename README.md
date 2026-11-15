# MCD2 Companion: loadout builder

A loadout builder for **Minecraft Dungeons II** that rebuilds the game's own inventory overview screen: level and item
power band on top, character on the left, the slot grid (Weapons, Armor, Artifacts, Talismans) in the middle and the
item tooltip on the right. Tap a slot to pick an item, then set rarity, item power, rolled effects, enchantment and
talisman level in the tooltip. Static HTML/CSS/JS; the build is saved in the URL (`#b=`) and localStorage.

## Build
```sh
python tools/build_data.py --strict    # ../_mcd2_extract -> data/data.js + assets/ (+ cache-bust stamp)
```
Needs Pillow and `fonttools` + `brotli` (game fonts are subset to Latin woff2). Preview with
`python ../tools/app/shot.py . out.png` (starts and stops its own server). Commits run `.githooks/pre-commit`
(`git config core.hooksPath .githooks` once per clone), which re-stamps `?v=` tokens in index.html.

## Layout
```
index.html  styles.css  app.js     # the app (app.js holds FEATURES)
data/data.js                       # GENERATED: window.MCD2
data/provenance.json               # GENERATED: shipped asset -> source file in the extract
assets/{items,effects,enchantments,ui,skins,fonts}/   # GENERATED from game files
tools/build_data.py
```

## Fidelity (where each piece comes from)
- Screen layout: `W_PlayerInventory`, `W_GearOverviewSlots` (4-column grid, section headers), `W_PlayerOverviewPanel`
  (Level / Item Power + Melee, Ranged, Armor, Artifacts / Effects & Stats), `W_Tooltip`, `W_TotalEffectsPanel`.
- Art: slot frame `T_UI_Slot_Background` (9-slice, margin 0.175), empty-slot silhouettes and category icons per
  `DefaultUIConfig.ini` EquipmentCategoryData, rarity badges, effect / enchantment / item icons, skin pose images.
- Colours: rarity = `DT_UIColorToken` Semantic.Item.*; level #C65BF5, item power #3AD3FF, effect #3AC6A9.
- Fonts: the game's FF_Spicewood faces (TenV2, Sixteen SemiBold, FiveV2 Bold) from the `.ufont` files.
- Text: every label from the game's string tables (`InventoryLabels`); effect values use each text entry's own
  number formatting (percent, multiplier, offset, digits).
- Rules: effect slots per rarity, effect pools per item (drop tables -> groups -> templates, rarity and
  incompatibility filters), unique fixed effects and built-in enchantments: `_mcd2_extract/code/PROCEDURAL_MAP.md`.

## Flagged (shown in the app with an orange marker and listed under the header's flag button)
Everything the game files do not supply is listed in `MCD2.flags` by the build: shader-drawn UI (item-power icon,
slot glow, rarity fill, tooltip frame) redrawn in CSS; 2D pose instead of the live 3D character; the headline item
power formula and effect stacking (app shows average / sum); armor base protection; enchantment level scaling and
which gear takes which enchantment; items or effects without an icon.

## Data
From the sibling `../_mcd2_extract` datamine (never shipped; G-extract-not-in-app). Only generated runtime files are
committed.
