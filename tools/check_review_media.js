async (page) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.getByRole('button', {name: 'Run regression checks', exact: true}).click();
  const result = page.locator('#results');
  const report = await result.innerText();
  if (await result.getAttribute('data-status') !== 'passed') throw new Error(report);
  if (errors.length) throw new Error(errors.join('; '));
  console.log(report);
}
