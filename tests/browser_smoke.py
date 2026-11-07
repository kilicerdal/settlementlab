"""Run against a fresh local server: python tests/browser_smoke.py."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

output=Path('artifacts')
output.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(viewport={'width':1440,'height':1100})
    context.tracing.start(screenshots=True,snapshots=True,sources=True)
    page=context.new_page()
    try:
        page.goto(os.getenv('SETTLEMENTLAB_URL','http://127.0.0.1:8080'))
        expect(page.get_by_role('heading',name='Every trade. Accounted for.')).to_be_visible()
        page.get_by_role('button',name='Run showcase scenario').click()
        expect(page.locator('#detail .badge')).to_have_text('EXCEPTION')
        if os.getenv('SETTLEMENTLAB_TEST_LOCAL_AI') == '1':
            page.get_by_role('button',name='Analyze exception with AI').click()
            expect(page.locator('.ai-report h3')).to_have_text('AI analysis · advisory only',timeout=65000)
            expect(page.locator('.ai-report')).to_contain_text('ollama-local')
            page.screenshot(path=str(output/'local-ai.png'),full_page=True)
        page.get_by_role('button',name='Match full allocation').click()
        expect(page.locator('#detail .badge')).to_have_text('MATCHED')
        page.get_by_role('button',name='Affirm instructions').click()
        expect(page.locator('#detail .badge')).to_have_text('AFFIRMED')
        page.get_by_role('button',name='Attempt settlement').click()
        expect(page.locator('#detail .badge')).to_have_text('FAILED')
        page.get_by_role('button',name='Provision demo balances').click()
        expect(page.locator('#detail pre')).to_contain_text('$427,500.00')
        page.get_by_role('button',name='Attempt settlement').click()
        expect(page.locator('#detail .badge')).to_have_text('SETTLED')
        page.get_by_role('button',name='Reconcile statement').click()
        expect(page.get_by_role('status')).to_contain_text('BALANCED')
        page.screenshot(path=str(output/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(output/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        print('Browser journey passed: exception → correction → failure → recovery → reconciliation')
    finally:
        context.tracing.stop(path=str(output/'journey.zip'))
        browser.close()
