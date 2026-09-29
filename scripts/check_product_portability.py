import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.tmp' / 'ux-review'
OUT.mkdir(parents=True, exist_ok=True)
BOARD = json.loads((ROOT / 'static/data/board.json').read_text(encoding='utf-8'))
IDS = [row['PLAYER_ID'] for row in BOARD['rows'][:2]]
NOTE = 'Jokić ★\n中文 <img src=x onerror="window.PWN=1">'
TARGETS = {str(IDS[0]): {'takeBy': 3, 'note': NOTE}, '99999999': {'takeBy': None, 'note': ''}}
BACKUP = {'format': 'fantasy-nba-watchlist', 'version': 1, 'season': '2026-27', 'targets': [dict(playerId=int(id), **target) for id, target in TARGETS.items()]}
KEY = 'fantasy-nba-draft-targets-v1'
errors = []

def payload(value):
    return {'name': 'watchlist.json', 'mimeType': 'application/json', 'buffer': json.dumps(value, ensure_ascii=False).encode()}

def stored(page):
    return page.evaluate('(key) => JSON.parse(localStorage.getItem(key) || "{}")', KEY)

def new_page(browser, blocked=False):
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    if not blocked:
        ctx.grant_permissions(['clipboard-read', 'clipboard-write'])
    if blocked:
        ctx.add_init_script("Storage.prototype.getItem = () => { throw new DOMException('blocked','SecurityError'); }; Storage.prototype.setItem = () => { throw new DOMException('blocked','SecurityError'); }; navigator.clipboard.writeText = async () => { throw new Error('blocked'); };")
    page = ctx.new_page()
    page.set_default_timeout(30000)
    page.on('pageerror', lambda e: errors.append(str(e)))
    return ctx, page

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx, page = new_page(browser)
    page.goto('http://127.0.0.1:8788/#board?query=Wemb&layout=table&preset=performance')
    expect(page.locator('#rows tr')).to_have_count(1)
    expect(page.locator('#board-sort')).to_have_value('rank')
    expect(page.locator('#column-preset')).to_have_value('performance')
    page.select_option('#column-preset', 'risk')
    page.go_back()
    expect(page.locator('#column-preset')).to_have_value('performance')
    page.go_forward()
    expect(page.locator('#column-preset')).to_have_value('risk')
    page.fill('#search', '')
    page.locator(f'#rows [data-player="{IDS[0]}"]').click()
    expect(page.locator('#player-dialog')).to_be_visible()
    assert f'player={IDS[0]}' in page.url
    player_url = page.url
    page.go_back()
    expect(page.locator('#player-dialog')).not_to_be_visible()
    page.go_forward()
    expect(page.locator('#player-dialog')).to_be_visible()
    page.reload()
    expect(page.locator('#player-dialog')).to_be_visible()
    page.locator('#player-dialog .dialog-close').click()
    expect(page).not_to_have_url(player_url)
    page.goto(f'http://127.0.0.1:8788/#compare?ids={IDS[0]},{IDS[1]},99999999')
    expect(page.locator('#compare-view')).to_contain_text('IDs absent')
    expect(page.locator('.compare-name')).to_have_count(2)
    page.locator('[data-remove="99999999"]').click()
    assert '99999999' not in page.url
    page.go_back()
    expect(page.locator('#compare-view')).to_contain_text('99999999')
    page.goto('http://127.0.0.1:8788/#compare?ids=abc')
    expect(page.locator('#route-note')).to_contain_text('positive player IDs')
    page.goto('http://127.0.0.1:8788/#board')
    page.locator('#watchlist-file').set_input_files(payload(BACKUP))
    expect(page.locator('#import-unknown')).to_contain_text('99999999')
    assert stored(page) == {}
    page.get_by_role('button', name='Cancel', exact=True).click()
    assert stored(page) == {}
    page.locator('#watchlist-file').set_input_files(payload(BACKUP))
    page.get_by_role('button', name='Confirm import', exact=True).click()
    assert stored(page) == TARGETS
    page.locator(f'#rows [data-player="{IDS[0]}"]').click()
    expect(page.locator('#player-detail')).to_contain_text(NOTE)
    assert not page.evaluate('Boolean(window.PWN)')
    page.locator('#player-dialog [data-copy-link]').click()
    expect(page.locator('.copy-status')).to_contain_text('Link copied')
    assert 'note' not in page.url and 'Joki' not in page.url
    page.keyboard.press('Escape')
    with page.expect_download() as dl:
        page.get_by_role('button', name='Export watchlist').click()
    dl.value.save_as(str(OUT / 'public-watchlist.json'))
    exported = json.loads((OUT / 'public-watchlist.json').read_text(encoding='utf-8'))
    assert exported['season'] == '2026-27' and exported['targets'] == BACKUP['targets']
    page.locator('#watchlist-file').set_input_files(payload({**BACKUP, 'version': 999}))
    expect(page.locator('#backup-status')).to_contain_text('version 1')
    assert stored(page) == TARGETS
    for width in [320, 390, 760]:
        page.set_viewport_size({'width': width, 'height': 844})
        expect(page.locator('.topbar [data-copy-link]')).to_be_visible()
        assert page.evaluate('document.body.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT / 'portability-public-mobile.png'))
    print('PASS: public route history, modal reload, unavailable IDs, Unicode export and invalid-import isolation', flush=True)
    ctx.close()

    ctx, page = new_page(browser)
    page.goto('http://127.0.0.1:8787/?preset=performance&q=Wemb&layout=table')
    expect(page.get_by_label('Table columns', exact=True)).to_have_value('performance')
    page.locator('.board-table-view input[type=checkbox]').first.wait_for(timeout=120000)
    assert page.locator('.board-table-view tbody tr:has(input)').count() == 1
    page.get_by_label('Table columns', exact=True).select_option('risk')
    page.go_back()
    expect(page.get_by_label('Table columns', exact=True)).to_have_value('performance')
    page.go_forward()
    expect(page.get_by_label('Table columns', exact=True)).to_have_value('risk')
    page.reload()
    expect(page.get_by_label('Table columns', exact=True)).to_have_value('risk')
    page.locator('input[type=file]').set_input_files(str(OUT / 'public-watchlist.json'))
    expect(page.get_by_role('dialog', name='Import watchlist')).to_contain_text('99999999')
    page.get_by_role('button', name='Confirm import').click()
    assert stored(page) == TARGETS
    with page.expect_download() as dl:
        page.get_by_role('button', name='Export watchlist').click()
    dl.value.save_as(str(OUT / 'local-watchlist.json'))
    assert json.loads((OUT / 'local-watchlist.json').read_text(encoding='utf-8'))['targets'] == BACKUP['targets']
    reverse = ctx.new_page()
    reverse.goto('http://127.0.0.1:8788/#board')
    reverse.locator('#watchlist-file').set_input_files(str(OUT / 'local-watchlist.json'))
    reverse.get_by_role('button', name='Confirm import').click()
    assert stored(reverse) == TARGETS
    reverse.locator('#watchlist-file').set_input_files(payload({**BACKUP, 'targets': []}))
    reverse.locator('[name=import-mode][value=replace]').check()
    reverse.get_by_role('button', name='Confirm import').click()
    assert stored(reverse) == {}
    reverse.close()
    page.goto(f'http://127.0.0.1:8787/compare?ids={IDS[0]},{IDS[1]},99999999')
    expect(page.get_by_role('button', name='Remove 99999999')).to_be_visible(timeout=120000)
    expect(page.get_by_role('heading', name='Compare', exact=True)).to_be_visible()
    page.get_by_role('button', name='Remove 99999999').click()
    assert '99999999' not in page.url
    page.go_back()
    expect(page.get_by_role('button', name='Remove 99999999')).to_be_visible()
    page.goto(f'http://127.0.0.1:8787/players/{IDS[0]}')
    expect(page.get_by_role('button', name='Copy link', exact=True)).to_be_visible(timeout=120000)
    expect(page.locator('main')).to_contain_text(NOTE)
    assert not page.evaluate('Boolean(window.PWN)')
    page.goto('http://127.0.0.1:8787/compare?ids=abc')
    expect(page.locator('main')).to_contain_text('positive player IDs')
    page.goto('http://127.0.0.1:8787/compare?ids=99999999')
    expect(page.get_by_role('button', name='Remove 99999999')).to_be_visible()
    page.get_by_role('button', name='Remove 99999999').click()
    expect(page).to_have_url('http://127.0.0.1:8787/compare?ids=')
    page.goto('http://127.0.0.1:8787/?layout=cards')
    page.locator('[data-player-card]').first.wait_for()
    before = stored(page)
    page.locator('input[type=file]').set_input_files(payload({**BACKUP, 'season': '2025-26'}))
    expect(page.locator('main')).to_contain_text('This backup is for 2025-26')
    assert stored(page) == before
    replacement = {**BACKUP, 'targets': [BACKUP['targets'][0]]}
    page.locator('input[type=file]').set_input_files(payload(replacement))
    page.get_by_label('Replace —', exact=False).check()
    page.get_by_role('button', name='Confirm import').click()
    assert stored(page) == {str(IDS[0]): TARGETS[str(IDS[0])]}
    for width in [320, 390, 760]:
        page.set_viewport_size({'width': width, 'height': 844})
        assert page.evaluate('document.body.scrollWidth <= innerWidth')
    page.screenshot(path=str(OUT / 'portability-local-mobile.png'))
    print('PASS: local route precedence/history, cross-app backup, replace, wrong-season protection and mobile fit', flush=True)
    ctx.close()

    for port in [8788, 8787]:
        ctx, page = new_page(browser, blocked=True)
        page.goto(f'http://127.0.0.1:{port}/')
        file = page.locator('#watchlist-file') if port == 8788 else page.locator('input[type=file]')
        file.wait_for(state='attached', timeout=120000)
        file.set_input_files(payload(BACKUP))
        page.get_by_role('button', name='Confirm import').click()
        expect(page.locator('main')).to_contain_text('session only')
        if port == 8788:
            page.locator(f'#rows .player-button[data-player="{IDS[0]}"]').click()
            page.locator('#player-dialog [data-copy-link]').click()
            expect(page.locator('.copy-fallback')).to_be_visible()
            assert NOTE not in page.locator('.copy-fallback').input_value()
        else:
            page.locator(f'.board-table-view button').filter(has_text=BOARD['rows'][0]['PLAYER_NAME']).first.click()
            expect(page.locator('main')).to_contain_text(NOTE)
            page.get_by_role('button', name='Copy link', exact=True).click()
            expect(page.get_by_label('Link to copy')).to_be_visible()
            assert NOTE not in page.get_by_label('Link to copy').input_value()
        ctx.close()
    assert not errors, errors
    print('PASS: blocked storage retains session targets across navigation; clipboard fallback; no script errors', flush=True)
    browser.close()
