"""Read-only browser verification. Never changes picks or the user's browser storage."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'data/processed/upside_review_2026-10-18'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--public', default='http://127.0.0.1:8788/')
    parser.add_argument('--public-only', action='store_true')
    args = parser.parse_args()
    errors = []
    surfaces = [('public', args.public)]
    if not args.public_only:
        surfaces.append(('local', 'http://127.0.0.1:8787/'))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for surface, url in surfaces:
            context = browser.new_context(viewport={'width':1440, 'height':1000})
            page = context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url)
            rows = page.locator('#rows tr' if surface=='public' else 'tbody tr')
            expect(rows).to_have_count(200, timeout=30000)
            expect(page.locator('#board-head' if surface=='public' else 'thead')).to_contain_text('Playoff games')
            expect(page.get_by_text('ESPN platform ADP', exact=False).first).to_be_visible()
            search = page.locator('#search') if surface=='public' else page.get_by_placeholder('Search player, team or position', exact=False)
            search.fill('Garland')
            expect(rows).to_have_count(1)
            page.get_by_role('button', name='Upside for Darius Garland', exact=True).click()
            detail = page.locator('[data-upside-detail]:visible')
            expect(detail).to_contain_text('Conditional upside: 41.9 FP/G')
            expect(detail).to_contain_text('earliest 42')
            expect(detail).to_contain_text('31.6 MPG')
            expect(detail).to_contain_text('Back-to-back second nights')
            page.screenshot(path=str(OUT/f'{surface}-upside.png'))
            page.keyboard.press('Escape')
            search.fill('')
            filters = page.locator('#radar-filter') if surface=='public' else page.locator('select').filter(has=page.locator('option[value="Breakouts"]')).first
            filters.select_option('Breakouts')
            expect(rows.first).to_contain_text('Breakout potential')
            assert all('Breakout potential' in text for text in rows.all_text_contents())
            filters.select_option('All')
            page.get_by_text('Extra flyer watchlist', exact=False).first.click()
            expect(page.get_by_text('Aday Mara', exact=False).first).to_be_visible()
            page.screenshot(path=str(OUT/f'{surface}-desktop.png'))
            page.set_viewport_size({'width':390, 'height':844})
            cards = page.locator('#board-cards .player-card' if surface=='public' else '[data-player-card]')
            expect(cards.first).to_contain_text('Playoffs:')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), surface+' board overflow'
            page.screenshot(path=str(OUT/f'{surface}-mobile.png'))
            page.set_viewport_size({'width':1440, 'height':1000})
            before = None
            if surface=='local':
                before = page.request.get(url+'api/draft/state?top=1000').json()
            page.goto(url+('#mock' if surface=='public' else 'room'))
            table = page.locator('#mock-rows' if surface=='public' else 'tbody').first
            first_profile = 'Established role'
            if before:
                first = min((r for r in before['board'] if r.get('draft_rank') is not None), key=lambda r:r['draft_rank'])
                first_profile = first['upside_profile']
            expect(table.locator('tr').first).to_contain_text(first_profile, timeout=30000)
            expect(page.locator('#view-mock thead' if surface=='public' else 'thead').first).to_contain_text('Playoff games')
            if surface=='local':
                table.locator('summary').first.click()
                expect(table.locator('[data-upside-detail]').first).to_be_visible()
                after = page.request.get(url+'api/draft/state?top=1000').json()
                assert before['picks']==after['picks'], 'Draft state changed'
            page.screenshot(path=str(OUT/f'{surface}-draft-room.png'))
            context.close()
        browser.close()
    assert not errors, errors
    (OUT/'browser-verification.json').write_text(json.dumps({'surfaces':surfaces,'javascript_errors':errors,'draft_picks_changed':False},indent=2))
    print('Both board layouts, upside details, filters, watchlist and draft rooms passed; no picks changed.')


if __name__=='__main__':
    main()
