async (page) => {
  page.setDefaultTimeout(5000);
  const failures = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const check = (ok, message) => { if (!ok) failures.push(message); };
  const select = (id, value) => page.locator(`#qr-${id}`).selectOption(value);
  const mark = id => page.locator(`#fragments .qr-change-target[data-review-ids~="${id}"]`);
  const badge = id => page.locator(`.qr-change-link[data-qr-target="${id}"]`);
  await page.reload();
  await page.locator('#qr-author-hint').waitFor();
  const decisions = await page.locator('#quarto-review .qr-suggestion').evaluateAll(items => items.map(i => [i.dataset.reviewId,i.dataset.status,i.dataset.author]));
  for (const width of [1600, 600]) {
    await page.setViewportSize({width, height:1000});
    await select('view', 'review');
    await select('kind', 'suggestion');
    await select('status', 'pending');
    await select('author', 'Author');
    check(await page.locator('#fragments').innerText() === 'Compare vboth involuntary and voluntary tests.', `${width}: marker splits fragmented word`);
    for (const id of ['f1','f2','f3']) {
      check(!await badge(id).isVisible(), `${width}: redundant ${id} badge`);
      check(await mark(id).getAttribute('tabindex') === '0', `${width}: ${id} lacks keyboard access`);
    }
    await mark('f2').click();
    check(await page.locator('.qr-card[data-review-id="f2"]:visible').count() > 0, `${width}: click lost review card`);
    await mark('f3').focus();
    await page.keyboard.press('Enter');
    check(await page.locator('.qr-card[data-review-id="f3"]:visible').count() > 0, `${width}: keyboard lost review card`);
    await page.locator('#qr-next').click();
    check(await page.locator('.qr-card[data-review-id="replacement"]:visible').count() > 0, `${width}: next skipped change after fragments`);
    await page.locator('#qr-previous').click();
    check(await page.locator('.qr-card[data-review-id="f3"]:visible').count() > 0, `${width}: previous skipped fragment`);
    await select('view','proposed');
    check(await badge('f1').isVisible(), `${width}: absent deletion lost point marker`);
    check(!await badge('f2').isVisible() && !await badge('f3').isVisible(), `${width}: Proposed has redundant insertion markers`);
    await select('view','original');
    check(!await badge('f1').isVisible(), `${width}: Original has redundant deletion marker`);
    check(await badge('f2').isVisible() && await badge('f3').isVisible(), `${width}: absent insertions lost point markers`);
    await select('author','Other');
    check(await page.locator('#fragments .qr-link:visible').count() === 0, `${width}: author filter leaked marker`);
    check(await page.locator('#fragments .qr-change-target').count() === 0, `${width}: author filter leaked keyboard target`);
    await select('author','Author');
    await select('view','review');
    await page.locator('#qr-toggle-comments').click();
    check(await page.locator('#fragments .qr-change-target').count() === 0, `${width}: hidden cards retain keyboard targets`);
    await page.locator('#qr-toggle-comments').click();
    check(await mark('f2').count() === 1, `${width}: restoring cards lost text target`);
    await page.locator('#qr-reading-view').click();
    check(await page.locator('#fragments').innerText() === 'Compare both involuntary and voluntary tests.', `${width}: clean reading changed text`);
    check(await page.locator('#fragments .qr-change-target').count() === 0, `${width}: Reading view contains review targets`);
    await page.locator('#qr-restore-review').click();
  }
  await page.getByRole('button', {name:'Run regression checks', exact:true}).click();
  check(await page.locator('#results').getAttribute('data-status') === 'passed', await page.locator('#results').innerText());
  check(JSON.stringify(await page.locator('#quarto-review .qr-suggestion').evaluateAll(items => items.map(i => [i.dataset.reviewId,i.dataset.status,i.dataset.author]))) === JSON.stringify(decisions), 'Decisions or attribution changed');
  check(!errors.length, errors.join('; '));
  if (failures.length) throw new Error(failures.join('\n'));
  return 'PASS: fragmented words remain readable; click/keyboard/navigation work; absent-text markers, filters and Reading view work at 1600px and 600px; all media checks pass; decisions and attribution unchanged.';
}
