async (page) => {
  page.setDefaultTimeout(5000);
  const failures = [];
  const errors = [];
  const check = (ok, message) => { if (!ok) failures.push(message); };
  page.on('pageerror', e => errors.push(e.message));
  const select = (name, value) => page.getByRole('combobox', {name, exact:true}).selectOption(value);
  const records = () => page.locator('#quarto-review article').evaluateAll(items => items.map(i => [i.dataset.reviewId,i.dataset.status,i.dataset.author]));
  const matches = () => page.locator('#quarto-review article').evaluateAll(items => items.filter(i => !i.hidden).map(i => i.dataset.reviewId).sort().join(','));
  const count = async text => check(await page.locator('#qr-count').innerText() === text, `Expected count ${text}`);
  const checkMatches = async (value, ids, text) => {
    await select('Status', value);
    check(await matches() === ids, `${value}: wrong matching records`);
    await count(text);
  };
  await page.reload();
  await page.locator('#qr-author-hint').waitFor();
  check(await page.locator('#qr-kind').inputValue() === '', 'Default review omits a type');
  check(await page.locator('#qr-status').inputValue() === 'open-pending', 'Default status is not open/pending');
  check(await matches() === 'c2,s1', 'Default matches include decided records');
  const before = await records();
  const options = {
    '': [['open-pending','Open comments + pending changes'], ['resolved-decided','Resolved comments + decided changes'], ['','All statuses']],
    comment: [['open','Open'], ['resolved','Resolved'], ['','All statuses']],
    suggestion: [['pending','Pending'], ['decided','Accepted or rejected'], ['accepted','Accepted'], ['rejected','Rejected'], ['','All statuses']],
  };
  const ids = {open:'c2', resolved:'c1', pending:'s1', accepted:'s2', rejected:'s3', decided:'s2,s3', 'open-pending':'c2,s1', 'resolved-decided':'c1,s2,s3'};
  // Explicit cross-type expectations, including the lossy single-decision cases.
  const transitions = [
    ['', 'open-pending', 'comment', 'open'], ['', 'open-pending', 'suggestion', 'pending'],
    ['comment', 'open', '', 'open-pending'], ['comment', 'open', 'suggestion', 'pending'],
    ['suggestion', 'pending', '', 'open-pending'], ['suggestion', 'pending', 'comment', 'open'],
    ['', 'resolved-decided', 'comment', 'resolved'], ['', 'resolved-decided', 'suggestion', 'decided'],
    ['comment', 'resolved', '', 'resolved-decided'], ['comment', 'resolved', 'suggestion', 'decided'],
    ['suggestion', 'decided', '', 'resolved-decided'], ['suggestion', 'decided', 'comment', 'resolved'],
    ['suggestion', 'accepted', '', 'resolved-decided'], ['suggestion', 'accepted', 'comment', 'resolved'],
    ['suggestion', 'rejected', '', 'resolved-decided'], ['suggestion', 'rejected', 'comment', 'resolved'],
  ];
  for (const width of [1600,600]) {
    await page.setViewportSize({width,height:1000});
    await select('Review','');
    await select('Status','');
    await count('2 comments, 3 changes');
    for (const [reviewKind, expected] of Object.entries(options)) {
      await select('Review', reviewKind);
      const actual = await page.locator('#qr-status option').evaluateAll(nodes => nodes.map(n => [n.value,n.textContent]));
      check(JSON.stringify(actual) === JSON.stringify(expected), `Wrong options for ${reviewKind || 'both'}`);
    }
    for (const [from, state, to, expected] of transitions) {
      await select('Review', from); await select('Status', state); await select('Review', to);
      check(await page.locator('#qr-status').inputValue() === expected, `${from}/${state} → ${to}: lost corresponding state`);
      check(await matches() === ids[expected], `${from}/${state} → ${to}: wrong records`);
    }
    for (const from of Object.keys(options)) {
      for (const to of Object.keys(options)) {
        await select('Review', from); await select('Status', ''); await select('Review', to);
        check(await page.locator('#qr-status').inputValue() === '', 'All statuses was not retained');
        check(await matches() === ({'':'c1,c2,s1,s2,s3',comment:'c1,c2',suggestion:'s1,s2,s3'})[to], 'All statuses lost records');
      }
    }
    await select('Review', '');
    await checkMatches('open-pending','c2,s1','1 comment, 1 change');
    await page.locator('.qr-change-target[data-review-ids~="s1"]').first().click();
    check(await page.locator('.qr-card[data-review-id="s1"]:visible').count() > 0, 'Pending edit under resolved comment cannot be inspected');
    await page.locator('#qr-next').click();
    check(await page.locator('.qr-card[data-review-id="c2"]:visible').count() > 0, 'Next failed to reach open comment');
    await page.locator('#qr-previous').click();
    check(await page.locator('.qr-card[data-review-id="s1"]:visible').count() > 0, 'Previous failed to reach pending change');
    await checkMatches('resolved-decided','c1,s2,s3','1 comment, 2 changes');
    for (const [reviewKind, value, expected, text] of [
      ['comment','open','c2','1 comment'],
      ['comment','resolved','c1','1 comment'],
      ['suggestion','pending','s1','1 change'],
      ['suggestion','decided','s2,s3','2 changes'],
      ['suggestion','accepted','s2','1 change'],
      ['suggestion','rejected','s3','1 change'],
    ]) {
      await select('Review',reviewKind);
      await checkMatches(value, expected, text);
    }
    await select('Review','');
    await select('Status','open-pending');
    await select('Author','Example Author');
    check(await matches() === '', 'Author filter leaked mismatching outstanding records');
    await count('0 comments, 0 changes');
    await select('Author','Example Reviewer');
    check(await matches() === 'c2,s1', 'Author filter hid matching outstanding records');
    await select('Author','');
    await select('Review','comment');
    check(await page.locator('#qr-status').inputValue() === 'open', 'Combined open/pending did not become Open');
    await select('Status','resolved');
    check(await matches() === 'c1', 'Resolved comment missing');
    await select('Review','suggestion');
    check(await page.locator('#qr-status').inputValue() === 'decided', 'Resolved did not become Accepted or rejected');
    await select('Status','pending');
    check(await matches() === 's1', 'Pending edit changed when its thread was resolved');
    await select('Review','');
    await select('Status','open-pending');
    await page.locator('#qr-reading-view').click();
    check(await page.locator('.qr-card:visible').count() === 0, 'Reading view exposed review cards');
    await page.locator('#qr-restore-review').click();
    check(await page.locator('#qr-status').inputValue() === 'open-pending', 'Restore lost combined filter');
    for (const view of ['original','proposed','review']) {
      await select('Text view', view);
      check(await matches() === 'c2,s1', `Text view ${view} changed status matches`);
    }
    check(JSON.stringify(await records()) === JSON.stringify(before), 'Filtering changed source decisions or attribution');
  }
  check(!errors.length, errors.join('; '));
  if (failures.length) throw new Error(failures.join('\n'));
  return 'PASS: combined defaults, type-specific menus, corresponding state translations, all-status retention, individual decisions, resolved-thread pending changes, counts, navigation, author filters, restoration and unchanged source records at 1600px and 600px.';
}
