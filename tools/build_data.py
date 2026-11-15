"""Build the MCD2 loadout builder's shipped data + assets from the sibling ../_mcd2_extract datamine.

usage: python tools/build_data.py [--strict]

Out:
  data/data.js          window.MCD2 = {...} (the only data file the app loads)
  data/provenance.json  every shipped asset -> its source PNG / font in the extract (not loaded by the app)
  assets/<group>/*.webp item, effect, enchantment, slot, UI and skin art (downscaled with Lanczos, never upscaled)
  assets/fonts/*.woff2  the game's own fonts (ufont = 4-byte prefix + OpenType), subset to Latin
Guards (rule A-provenance-guards): every asset path written into data.js must exist on disk and carry a provenance entry;
every gap (no art, no text, undecoded rule) is listed in MCD2.flags and shown in the app. --strict turns any guard
error into a non-zero exit with nothing written.
"""
import hashlib
import io
import json
import os
import re
import sys

from PIL import Image

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
X = os.path.join(os.path.dirname(APP), '_mcd2_extract')
TAB = os.path.join(X, 'data', 'app', 'tables')
UFS = os.path.join(X, 'data', 'raw', 'Dungeons', 'Content', 'Spicewood', 'Core', 'DataTables', 'UFS')
TEX = os.path.join(X, 'assets', 'tex', 'Dungeons')
STRICT = '--strict' in sys.argv

errors, flags, prov = [], [], {}


def load(*p):
    with open(os.path.join(*p), encoding='utf-8') as f:
        return json.load(f)


ENT = load(X, 'data', 'app', 'entities.json')
ROLLS = load(TAB, 'rolls.json')
EFFECTS = load(TAB, 'effects.json')
LABELS = load(X, 'data', 'app', 'labels.json')
LOC = load(X, 'data', 'loc', 'en.json')
INV = LOC['Text/Release/InventoryLabels.csv']


def flag(area, what, ids=None):
    flags.append({'area': area, 'what': what, **({'ids': ids} if ids else {})})


# ---------------------------------------------------------------- assets
def ship(src, group, name=None, size=None):
    """Copy an extract PNG to assets/<group>/<name>.webp (lossless, optional Lanczos downscale). Returns app path."""
    if src is None:
        return None
    full = src if os.path.isabs(src) else os.path.join(X, src)
    if not os.path.isfile(full):
        errors.append(f'missing source image {src}')
        return None
    name = name or os.path.splitext(os.path.basename(full))[0]
    rel = f'assets/{group}/{name}.webp'
    out = os.path.join(APP, rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    im = Image.open(full).convert('RGBA')
    if size and max(im.size) > size:  # downscale only (G-no-ai-scaler: never upscale)
        im = im.resize((size, size) if im.width == im.height else
                       (size, round(im.height * size / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, 'WEBP', lossless=True, quality=100, method=6)
    data = buf.getvalue()
    if not os.path.isfile(out) or open(out, 'rb').read() != data:
        with open(out, 'wb') as f:
            f.write(data)
    prov[rel] = os.path.relpath(full, X).replace('\\', '/')
    return rel


def tex(path):
    """'/Game/Spicewood/X/T_Y.T_Y' | '/OreUI/UI/X/T_Y...' | '/SpicewoodUI/Spicewood/...' -> extract PNG path."""
    p = path.split('.')[0]
    for pre, rep in (('/Game/', 'Content/'), ('/OreUI/', 'Plugins/OreUI/Content/'),
                     ('/SpicewoodUI/', 'Plugins/SpicewoodUI/Content/')):
        if p.startswith(pre):
            return os.path.join(TEX, rep + p[len(pre):] + '.png')
    return None


def ver(rel):
    """Cache-bust token for an image path (rule A-cache-bust: image ?v= is set in the data build)."""
    if not rel:
        return None
    h = hashlib.md5(open(os.path.join(APP, rel), 'rb').read()).hexdigest()[:8]
    return f'{rel}?v={h}'


# ---------------------------------------------------------------- tag model
def parents(tag):
    e = ENT.get(tag)
    return (e or {}).get('parents') or []


def ancestry(tags):
    """All tags reachable through trait parents + every dotted prefix (GameplayTag hierarchy)."""
    seen, stack = set(), list(tags)
    while stack:
        t = stack.pop()
        if t in seen or not t:
            continue
        seen.add(t)
        stack.extend(parents(t))
        parts = t.split('.')
        stack.extend('.'.join(parts[:i]) for i in range(1, len(parts)))
    return seen


def kv_named(facet):
    """KeyValues with their TypeTag names (entities.json keeps them; the app tables drop them)."""
    out = {}
    for kv in (facet or {}).get('KeyValues', []) or []:
        name = (kv.get('TypeTag') or {}).get('TagName', '').replace('SW.KeyValue.', '')
        t = kv.get('Type')
        v = kv.get(t) if t else None
        if isinstance(v, dict) and 'GameplayTags' in v:
            v = [x['TagName'] for x in v['GameplayTags']]
        elif isinstance(v, dict) and 'TagName' in v:
            v = v['TagName']
        out[name] = v
    return out


# ---------------------------------------------------------------- text formatting (labels.json text_templates)
def fmt_of(tag, entry='SW.TextEntry.Description'):
    """Number formatting for {0} of a description (game data, PROCEDURAL_MAP section 10)."""
    tt = LABELS['text_templates']
    chain = [tag] + list(parents(tag))
    for t in chain:
        e = (tt.get(t) or {}).get(entry)
        if e and e.get('values'):
            v = e['values'][0]
            return {'pct': v['IsPercentage'], 'sign': v['AlwaysSign'], 'mul': v['Multiplier'], 'off': v['Offset'],
                    'minf': v['MinFractionalDigits'], 'maxf': v['MaxFractionalDigits'], 'get': e['getter'].split('.')[-1],
                    'key': v['extract_from']}
    return None


def label(tag):
    v = LABELS['labels'].get(tag)
    if not v:
        return None, False
    return v['name'].get('en'), bool(v.get('internal'))


# ---------------------------------------------------------------- effects (rolled + unique + talisman)
templates = ROLLS['templates']
TEMPLATE_ROWS = {r['TypeTag']['TagName']: r for r in load(UFS, 'DT_EffectTemplateDefinition.json')}
TIER = {'SW.EffectTemplate.Tier1': 'I', 'SW.EffectTemplate.Tier2': 'II', 'SW.EffectTemplate.Tier3': 'III',
        'SW.EffectTemplate.TierUnique': 'U'}


def tpl_inherited(tag, field):
    """First template row (self, then trait parents depth-first) carrying `field` in TemplateData / KeyValues."""
    seen, stack = set(), [tag]
    while stack:
        t = stack.pop(0)
        if t in seen:
            continue
        seen.add(t)
        row = TEMPLATE_ROWS.get(t) or {}
        if field == 'query':
            q = (row.get('TemplateData') or {}).get('IncompatibleTagsQuery')
            if q and q.get('QueryTokenStream'):
                return q
        elif field == 'rarities':
            kv = kv_named(row).get('PossibleRarities')
            if kv:
                return kv
        stack.extend(x['TagName'] for x in ((row.get('Traits') or {}).get('GameplayTags') or []))
    return None


def query_fn(q):
    """FGameplayTagQuery token stream -> predicate over an item's tag set (ANY / ALL / NONE of tags or sub-exprs)."""
    if not q:
        return None
    toks, dic = q['QueryTokenStream'], [d['TagName'] for d in q['TagDictionary']]
    pos = [1]  # token 0 = version; then has-root-expression flag

    def nxt():
        v = toks[pos[0]]
        pos[0] += 1
        return v

    def expr():
        kind = nxt()  # 1 AnyTagsMatch 2 AllTagsMatch 3 NoTagsMatch 4 AnyExpr 5 AllExpr 6 NoExpr
        n = nxt()
        if kind <= 3:
            tags = [dic[nxt()] for _ in range(n)]
            if kind == 1:
                return lambda s: any(t in s for t in tags)
            if kind == 2:
                return lambda s: all(t in s for t in tags)
            return lambda s: not any(t in s for t in tags)
        subs = [expr() for _ in range(n)]
        if kind == 4:
            return lambda s: any(f(s) for f in subs)
        if kind == 5:
            return lambda s: all(f(s) for f in subs)
        return lambda s: not any(f(s) for f in subs)

    if nxt() == 0:
        return None
    return expr()


def effect_category(etag):
    for c in ancestry([etag]):
        if c.startswith('SW.EffectCategory.'):
            return c.split('.')[-1]
    return None


eff_out, tpl_out = {}, {}
ICONLESS = set()


def ensure_effect(etag):
    if etag in eff_out:
        return etag
    e = EFFECTS.get(etag)
    if not e:
        errors.append(f'effect {etag} not in effects.json')
        return None
    icon = ship(e['icon'], 'effects') if e.get('icon') else None
    if not icon:
        ICONLESS.add(etag)
    eff_out[etag] = {'n': e['name'], 'd': e['desc'], 'i': ver(icon), 'f': fmt_of(etag),
                     'c': effect_category(etag), 'lb': e.get('lower_is_better', False)}
    return etag


QUERY = {}


def ensure_template(ttag):
    if ttag in tpl_out:
        return ttag
    t = templates.get(ttag)
    if not t:
        errors.append(f'template {ttag} not in rolls.json')
        return None
    d = t['data']
    etag = ensure_effect(d['Effect'])
    tier = next((TIER[x] for x in t['traits'] if x in TIER), None)
    rar = tpl_inherited(ttag, 'rarities')
    QUERY[ttag] = query_fn(tpl_inherited(ttag, 'query'))
    tpl_out[ttag] = {'e': etag, 't': tier,
                     'v': d['FixedEffectValue'] if d['HasFixedEffectValue'] else None,
                     'r': [d['EffectMinValue'], d['EffectMaxValue']] if not d['HasFixedEffectValue'] else None,
                     'ip': d['MinimumRequiredItemPower'] or 0,
                     'ra': [x.split('.')[-1] for x in rar] if rar else None}
    return ttag


# ---------------------------------------------------------------- effect pools (PROCEDURAL_MAP 4.5)
DROP = ROLLS['drop_tables']
GROUPS = ROLLS['groups']


def drop_row(tag):
    """Row lookup with inheritance (PROCEDURAL_MAP 6): own row, else the first parent (list order) that has one."""
    seen, stack = set(), [tag]
    while stack:
        t = stack.pop(0)
        if t in seen:
            continue
        seen.add(t)
        if t in DROP:
            return DROP[t]
        stack.extend(parents(t))
    return None


def pool_for(item_tag, traits, tagset):
    groups = {}
    for ctx in [item_tag] + traits:
        row = drop_row(ctx)
        for g in (row or {}).get('primary', []):
            groups[g['tag']] = max(groups.get(g['tag'], 0), g['weight'])  # Set keeps the higher weight
    tw = {}
    for g, gw in groups.items():
        for t in GROUPS.get(g, {}).get('templates', []):
            tw[t['tag']] = max(tw.get(t['tag'], 0), t['weight'] * gw)
    out = []
    for ttag, w in tw.items():
        if not ensure_template(ttag):
            continue
        q = QUERY.get(ttag)
        if q and q(tagset):
            continue  # IncompatibleTagsQuery matches the item -> removed
        out.append([ttag, round(w, 4)])
    out.sort(key=lambda x: (eff_out[tpl_out[x[0]]['e']]['n'], tpl_out[x[0]]['t'] or ''))
    return out


# ---------------------------------------------------------------- items
SLOT_KIND = {'SW.Item.Property.Armor.Helmet': 'helmet', 'SW.Item.Property.Armor.Chest': 'chest',
             'SW.Item.Property.Armor.Leggings': 'legs', 'SW.Item.Property.Armor.Boots': 'boots'}
items, pools, pool_ix, skipped = [], [], {}, []


def facet_of(tag, table):
    return ((ENT.get(tag) or {}).get('facets') or {}).get(table) or {}


def add_items(cat, table):
    for it in load(TAB, cat + '.json'):
        tag, traits = it['tag'], it['traits']
        if not it.get('name'):
            skipped.append(tag)
            continue
        if cat == 'armor':
            kind = next((SLOT_KIND[t] for t in traits if t in SLOT_KIND), None)
            if not kind:
                skipped.append(tag)
                continue
        else:
            kind = cat
        f = facet_of(tag, table)
        kv = kv_named(f)
        tagset = ancestry([tag] + traits)
        rec = {'id': tag, 'k': kind, 'n': it['name'], 'd': it.get('desc')}
        icon = ship(it['icon'], 'items', size=128) if it.get('icon') else None
        rec['i'] = ver(icon)
        if not icon:
            flag('item', 'No icon in the game files', [tag])
        unique = kv.get('PossibleRarities') == ['SW.Rarity.Unique'] or re.search(r'_Unique\d*$', tag) is not None
        rec['u'] = 1 if unique else 0
        listed = it['properties'].get(table, {}).get('Effects') or []
        fixed = [t for t in listed if not t.startswith('SW.Enchantment.') and ensure_template(t)]
        if fixed:
            rec['fx'] = fixed
        built_in = [t for t in listed if t.startswith('SW.Enchantment.') and ensure_ench(t, True)]
        if built_in:
            rec['ue'] = built_in[0]
        arch = sorted(t.split('.')[-1] for t in traits if t.startswith('SW.Archetype.'))
        if arch:
            rec['a'] = arch
        el = [t.split('.')[-1] for t in traits if t.startswith('SW.Item.Property.Elemental.')]
        if el:
            rec['el'] = el
        wc = [t.split('.')[-1] for t in traits if t.endswith(('LightArmor', 'MediumArmor', 'HeavyArmor', 'HeavyWeapon'))]
        if wc:
            rec['w'] = wc[0]
        aset = [t for t in traits if t.startswith('SW.Item.ArmorSet.')]
        if aset:
            rec['set'] = aset[0].split('.')[-1]
        if cat == 'artifact':
            if 'CooldownDuration' in kv:
                rec['cd'] = kv['CooldownDuration']
            if 'SoulArtifact.ActivationCost' in kv:
                rec['soul'] = kv['SoulArtifact.ActivationCost']
        if cat == 'talisman':
            rec['lv'] = []
            for L in it.get('levels') or []:
                ic = ship(L['icon'], 'items', size=128) if L.get('icon') else None
                rec['lv'].append({'i': ver(ic), 'xp': L.get('xp_to_next'),
                                  'fx': [e['template'] for e in L['effects'] if ensure_talisman_template(e)]})
            if rec['lv'] and rec['lv'][0]['i']:
                rec['i'] = rec['lv'][0]['i']
        else:
            pool = pool_for(tag, traits, tagset)
            key = json.dumps(pool)
            if key not in pool_ix:
                pool_ix[key] = len(pools)
                pools.append(pool)
            rec['p'] = pool_ix[key]
        items.append(rec)


def ensure_talisman_template(e):
    """Talisman level effects live in DT_TalismanEffectTemplateDefinition (fixed values, tagged by level)."""
    t = e['template']
    if t not in tpl_out:
        etag = ensure_effect(e['effect'])
        if not etag:
            return False
        tpl_out[t] = {'e': etag, 't': None, 'v': e.get('fixed'), 'r': None if e.get('fixed') is not None
                      else [e.get('min'), e.get('max')], 'ip': e.get('min_item_power') or 0, 'ra': None}
    return True


# ---------------------------------------------------------------- enchantments (books -> enchantment + tiers)
ench = {}
EFF_CI = {k.lower(): k for k in EFFECTS}


def ensure_ench(tag, unique=False):
    """Enchantment entry from its effects.json row; {0} value from the ability key value the text getter names."""
    if tag in ench:
        return tag
    e = EFFECTS.get(tag)
    if not e:
        errors.append(f'enchantment {tag} not in effects.json')
        return None
    f = fmt_of(tag)
    val = None
    if f and f['get'] == 'GetAbilityKeyValues':
        short = f['key'].replace('SW.KeyValue.', '')
        for src in [tag] + parents(tag):
            for ab in (EFFECTS.get(src) or {}).get('abilities') or []:
                if short in (ab.get('specific') or {}):
                    val = ab['specific'][short]
                    break
            if val is not None:
                break
    icon = ship(e['icon'], 'enchantments') if e.get('icon') else None
    if not icon:
        ICONLESS.add(tag)
    tiers = [t for t in e.get('tiers') or [] if re.search(r'\.(I|II|III)$', t)]
    ench[tag] = {'n': e['name'], 'd': e['desc'], 'dl': e['texts'].get('SW.TextEntry.Description.Long'),
                 'i': ver(icon), 'f': f, 'v': val, 'c': effect_category(tag), 'tiers': len(tiers) or 3}
    if unique:
        ench[tag]['u'] = 1
    return tag


for b in load(TAB, 'enchantment_book.json'):
    kv = kv_named(facet_of(b['tag'], 'DT_ItemDefinitionEnchantmentBook'))
    first = next((v for v in kv.values() if isinstance(v, str) and v.startswith('SW.Enchantment.')), None)
    if not first or not b.get('name'):
        continue
    base = EFF_CI.get(first.rsplit('.', 1)[0].lower())
    if not base:
        errors.append(f'enchantment for book {b["tag"]} ({first}) not in effects.json')
        continue
    ensure_ench(base)
for cat, table in (('melee', 'DT_ItemDefinitionMelee'), ('ranged', 'DT_ItemDefinitionRanged'),
                   ('armor', 'DT_ItemDefinitionArmor'), ('artifact', 'DT_ItemDefinitionArtifact'),
                   ('talisman', 'DT_ItemDefinitionTalisman')):
    add_items(cat, table)

flag('enchantment', 'Which gear each enchantment can go on is not decoded yet; the builder allows any enchantment on any '
     'weapon, armor piece or artifact.')
flag('enchantment', 'How an enchantment grows from level I to III is not decoded yet; the number shown is the game\'s '
     'base value for every level.')

# ---------------------------------------------------------------- rarities
COLOR_ROWS = {r['Name']: r['Color'] for r in load(UFS, 'DT_UIColorToken.json')}
rar = []
for r in ('Common', 'Rare', 'Special', 'Unique'):
    row = ROLLS['rarities'][f'SW.Rarity.{r}']
    c = COLOR_ROWS[f'SW.UI.DesignToken.Color.Semantic.Item.{r}']
    rar.append({'id': r, 'n': INV[f'SW_Rarity_{r}'], 'c': '#%02X%02X%02X' % (c['R'], c['G'], c['B']),
                'fx': row['NumberOfEffectsData']['BaseNumberOfRerollableEffects'],
                'ipo': row['ItemPowerGenerationOffset'],
                'badge': ver(ship(os.path.join(TEX, f'Plugins/OreUI/Content/UI/Rarity/T_UI_Rarity_{r}.png'), 'ui',
                                  f'rarity_{r.lower()}'))})

# ---------------------------------------------------------------- slots + UI art (DefaultUIConfig.ini EquipmentCategoryData)
PI = 'Plugins/SpicewoodUI/Content/Spicewood/UI/Widget/Inventory/PlayerInventory/'
CATI = 'Plugins/OreUI/Content/UI/Icons/Categories/'


def ui(rel, name, size=None):
    return ver(ship(os.path.join(TEX, rel), 'ui', name, size))


empty = {k: ui(f'{PI}EmptyCategoryIcons/T_UI_Icon_{v}.png', f'empty_{k}') for k, v in
         (('melee', 'Melee'), ('ranged', 'Ranged'), ('helmet', 'Helmet'), ('chest', 'Breast'), ('legs', 'Legs'),
          ('boots', 'Boots'), ('artifact', 'Artifact'), ('talisman', 'Talisman'))}
cat_icon = {k: ui(f'{CATI}T_UI_Icon_Category_{v}.png', f'cat_{k}') for k, v in
            (('melee', 'Melee'), ('ranged', 'Ranged'), ('helmet', 'Helmet'), ('chest', 'Chest'), ('legs', 'Legs'),
             ('boots', 'Boots'), ('artifact', 'Potion'), ('talisman', 'Talisman'), ('weapons', 'Weapons'),
             ('armor', 'Shield'), ('stats', 'Stats'), ('effects', 'Effects'), ('enchantment', 'Enchantment'),
             ('all', 'All'))}
SLOT_LABEL = {'melee': INV['Equipment_Melee'], 'ranged': INV['Equipment_Ranged'], 'helmet': INV['Equipment_Helmet'],
              'chest': INV['Equipment_Chest'], 'legs': INV['Equipment_Leggings'], 'boots': INV['Equipment_Boots']}
sections = [
    {'id': 'weapons', 'n': INV['header_weapons'], 'i': cat_icon['weapons'], 'slots': ['melee', 'ranged']},
    {'id': 'armor', 'n': INV['header_armor'], 'i': cat_icon['armor'], 'slots': ['helmet', 'chest', 'legs', 'boots']},
    {'id': 'artifacts', 'n': INV['header_artifacts'], 'i': cat_icon['artifact'], 'slots': ['artifact'] * 3},
    {'id': 'talismans', 'n': INV['header_talismans'], 'i': cat_icon['talisman'], 'slots': ['talisman'] * 3},
]
ui_art = {
    'slot': ui('Plugins/OreUI/Content/UI/Button/SlotFrame/T_UI_Slot_Background.png', 'slot_frame'),
    'plus': ui('Content/Spicewood/UI/HUD/Player/Hotbar/Artifacts/Slot/T_UI_ArtifactEmpty_Dark.png', 'slot_plus'),
    'effectFrame': ui('Plugins/OreUI/Content/UI/Widget/Tooltip/Modules/Components/T_UI_EffectFrame.png', 'effect_frame'),
    'timer': ui('Plugins/OreUI/Content/UI/Widget/Tooltip/Modules/T_UI_Icon_Timer.png', 'icon_timer'),
    'soul': ui('Plugins/OreUI/Content/UI/Widget/Tooltip/Modules/T_UI_Icon_Soul_Cost.png', 'icon_soul'),
    'enchSwirl': ui('Plugins/OreUI/Content/UI/Icons/Currency/T_UI_Icon_EnchantmentSwirl.png', 'icon_enchant'),
    'talLevel': ui('Plugins/OreUI/Content/UI/Widget/Tooltip/Modules/T_UI_TalismanLevel.png', 'talisman_level'),
    'cat': cat_icon, 'empty': empty,
}
flag('ui', 'The item-power icon, slot glow, rarity slot fill and tooltip frame are drawn by in-game shaders with no image '
     'file; the app redraws them from the shader colours.')
flag('ui', 'The game shows a live 3D character here; the app uses the skin\'s 2D pose image instead.')
flag('stats', 'How the game turns the per-slot item powers into the headline Item Power is not decoded yet; the app shows '
     'the average of the equipped items.')
flag('stats', 'Effect totals are shown as the plain sum of equipped values; how the game stacks repeated effects is not '
     'decoded yet.')
flag('stats', 'Armor base protection by weight class (light / medium / heavy) is not in the game data tables.')
flag('effects', 'Possible effects per item follow the decoded roll tables (item type, archetype and element); which extra '
     'context tags a drop adds is not decoded yet.')

# ---------------------------------------------------------------- skins (pose images stand in for the 3D render)
skins = []
for tag, e in ENT.items():
    if e['kind'] != 'Skin' or not e.get('name'):
        continue
    pose = next((f.get('PoseTexture') for f in e['facets'].values() if isinstance(f, dict) and f.get('PoseTexture')),
                None)
    p = tex(pose) if pose else None
    img = ver(ship(p, 'skins')) if p and os.path.isfile(p) else None
    if not img:
        flag('skin', 'No pose image', [tag])
        continue
    skins.append({'id': tag, 'n': e['name'].replace(' Skin', ''), 'i': img})
skins.sort(key=lambda s: (s['id'] != 'SW.Skin.Tank', s['n']))

# ---------------------------------------------------------------- fonts (FF_Spicewood: TenV2 / Sixteen SemiBold / FiveV2 Bold)
FONT_SRC = os.path.join(X, 'data', 'raw', 'Dungeons', 'Content', 'Spicewood', 'Fonts', 'Spicewood')
fonts = {}
try:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    for key, fn in (('ten', 'Font_Spicewood_TenV2_Regular'), ('sixteen', 'Font_Spicewood_Sixteen_SemiBold'),
                    ('five', 'Font_Spicewood_FiveV2_Bold')):
        raw = open(os.path.join(FONT_SRC, fn + '.ufont'), 'rb').read()
        otf = raw[4:] if raw[4:8] in (b'OTTO', b'\x00\x01\x00\x00') else raw
        f = TTFont(io.BytesIO(otf))
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.layout_features = ['*']
        s = subset.Subsetter(opts)
        s.populate(unicodes=list(range(0x20, 0x250)) + [0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022,
                                                        0x2026, 0x2190, 0x2191, 0x2192, 0x2193, 0x00D7])
        s.subset(f)
        rel = f'assets/fonts/{key}.woff2'
        os.makedirs(os.path.join(APP, 'assets', 'fonts'), exist_ok=True)
        buf = io.BytesIO()
        f.flavor = 'woff2'
        f.save(buf)
        with open(os.path.join(APP, rel), 'wb') as o:
            o.write(buf.getvalue())
        prov[rel] = f'data/raw/Dungeons/Content/Spicewood/Fonts/Spicewood/{fn}.ufont'
        fonts[key] = ver(rel)
except ImportError:
    errors.append('fontTools not installed (pip install fonttools brotli): game fonts not built')

# ---------------------------------------------------------------- strings
ui_text = {k: INV[k] for k in ('header_weapons', 'header_armor', 'header_artifacts', 'header_talismans', 'header_level',
                              'header_gear_power', 'header_gear_low_power', 'inventory_totaleffects_toggle',
                              'effect_defensive', 'effect_offensive', 'effect_utility', 'Label_Enchantment',
                              'header_enchantments', 'tag_equipped', 'Label_Enchanted', 'Label_NotEnchanted')
           if k in INV}
for k in ('inventory_totaleffects_all', 'inventory_totaleffects_effects', 'inventory_totaleffects_enchantments'):
    if k in INV:
        ui_text[k] = INV[k]

# ---------------------------------------------------------------- guards + write
for rel in list(prov):
    if not os.path.isfile(os.path.join(APP, rel)):
        errors.append(f'asset written but missing on disk: {rel}')


def walk_paths(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from walk_paths(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk_paths(v)
    elif isinstance(o, str) and o.startswith('assets/'):
        yield o


if ICONLESS:
    flag('effect', 'No icon in the game files', sorted(ICONLESS))
if skipped:
    flag('item', 'Internal base rows without a name are left out', sorted(skipped))

const = ROLLS['item_creator_constants']['SW.GameplayRuleSet.SecondPass']
out = {
    'ui': ui_text, 'art': ui_art, 'fonts': fonts, 'sections': sections, 'slotLabel': SLOT_LABEL,
    'rarities': rar, 'items': items, 'pools': pools, 'templates': tpl_out, 'effects': eff_out,
    'enchantments': ench, 'skins': skins, 'flags': flags,
    'rules': {'maxEffects': const['NumberOfEffectsMax'], 'ipPerLevel': 1.5},
}
for p in walk_paths(out):
    if not os.path.isfile(os.path.join(APP, p.split('?')[0])):
        errors.append(f'data.js references missing file {p}')
    elif p.split('?')[0] not in prov:
        errors.append(f'asset without provenance {p}')

for e in errors:
    print('ERROR', e)
if errors and STRICT:
    sys.exit(1)
os.makedirs(os.path.join(APP, 'data'), exist_ok=True)
with open(os.path.join(APP, 'data', 'data.js'), 'w', encoding='utf-8', newline='\n') as f:
    f.write('window.MCD2=' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
with open(os.path.join(APP, 'data', 'provenance.json'), 'w', encoding='utf-8', newline='\n') as f:
    json.dump(prov, f, indent=1, sort_keys=True)
kinds = {}
for i in items:
    kinds[i['k']] = kinds.get(i['k'], 0) + 1
print(f'items {len(items)} {kinds} | pools {len(pools)} | templates {len(tpl_out)} | effects {len(eff_out)} | '
      f'enchantments {len(ench)} | skins {len(skins)} | assets {len(prov)} | flags {len(flags)} | errors {len(errors)}')
stamp = os.path.join(os.path.dirname(APP), 'tools', 'app', 'stamp_cache.py')
if os.path.isfile(stamp) and os.path.isfile(os.path.join(APP, 'index.html')):
    os.system(f'python "{stamp}" "{APP}"')
