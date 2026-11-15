# MCD2 Loadout Builder: progress

## State (2026-11-15)
- v1 local: inventory overview rebuilt (header band, character pose, 12-slot grid, tooltip editor), item / effect /
  enchantment / skin pickers, Effects & Stats totals with All / Effects / Enchantments filters, data notes (flags).
- Data: 296 items (58 melee, 22 ranged, 152 armor, 40 artifacts, 24 talismans), 51 distinct effect pools,
  302 effect templates, 40 enchantments (9 unique built-ins), 28 skins. Build: 0 errors.
- Every base item with a unique twin (all weapons and armor; artifacts and talismans have none) lists once, as the unique; the panel's rarity row swaps between base and unique (Common-Special = base, Unique = unique; data link UniqueSubstitution).
- Weapon Stats (collapsible, below the tooltip): melee per combo step (damage, hit time, step time, speed multiplier), combo damage / time / damage per second, reach, splash, jump attack, combo reset, on-hit statuses; ranged shot interval, arrows, damage factor, charge, ammo, reload. Speed decoded (extract PROCEDURAL_MAP 11) and follows equipped Swiftness / Reload. Level cap 100 from DT_PlayerDefinition LevelMax.
- Picker = list of tiles: slot art, name, built-in effect / enchantment, key numbers (melee combo damage, hits, time, DPS; ranged shot interval, damage factor, arrows, ammo; artifact description, cooldown, souls). Descriptions fill every placeholder ({1}+ from ability key values); enchantments whose number is the level magnitude use the I / II / III values.
- Back button: every open menu level is a history entry (device / browser back, Esc, in-menu ‹ step back one level; close / backdrop drop all levels); on the base screen back is normal page history. Verified with tools/app/flow.py (base screen = history entry 0).
- Mobile first: phone = stacked band / character / grid, tooltip as bottom sheet; >= 1000 px = the game's 3 columns.

## Open
- [x] GitHub repo misterwtheface-oss/mcd2-companion, Pages from main root (auto-deploys on push)
- [ ] Headline Item Power aggregation (`EItemPowerCategory::Total`, GetPlayerItemPower `0x146155280` -> `0x14617ceb0`,
      category -> attribute map `0x146179e30`); app shows the average of equipped items
- [ ] Effect stacking for the totals panel (EffectTotal text uses attribute value + Offset); app shows the sum
- [ ] Enchantment I-III scaling for ability-based enchantments (level-magnitude ones done) and per-gear applicability; 5 descriptions read live state ({0}/{1} shown as ?)
- [ ] Armor base protection by weight class; item-power factor on weapon damage (PROCEDURAL_MAP 8, needs threat)
- [ ] Arrow base damage (not in data); queued-attack cancel timing in combos; Short Spear has 3 hits but 2 animation sections
- [ ] Cosmetics (cape, pet) live on a separate game screen; potion slot only on the HUD
