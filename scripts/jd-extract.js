(() => {
  const q = (s) => document.querySelector(s);
  const norm = (s) => (s || '').replace(/[ \t]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
  const txt = (el) => el ? norm(el.innerText || '') : '';
  const top = q('.job-details-jobs-unified-top-card__container--two-pane')
    || q('.jobs-unified-top-card')
    || q('.job-details-jobs-unified-top-card')
    || document.body;
  const title = txt(q('h1'))
    || txt(q('.job-details-jobs-unified-top-card__job-title'))
    || txt(q('.jobs-unified-top-card__job-title'));
  const company = txt(q('.job-details-jobs-unified-top-card__company-name'))
    || txt(q('.jobs-unified-top-card__company-name'))
    || '';
  const primary = txt(q('.job-details-jobs-unified-top-card__primary-description-container'));
  const tertiary = txt(q('.job-details-jobs-unified-top-card__tertiary-description-container'));
  const wpType = txt(q('.job-details-jobs-unified-top-card__workplace-type'))
    || txt(q('.jobs-unified-top-card__workplace-type'));
  const desc = txt(q('#job-details'))
    || txt(q('.jobs-description__content'))
    || txt(q('.jobs-box__html-content'))
    || txt(q('.jobs-description'));
  const pageText = norm(document.body.innerText || '');
  const applyLabels = [...document.querySelectorAll('button,a,span')]
    .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
    .filter(t => /^(Enviar candidatura|Candidatar-se|Candidatura simplificada|Easy Apply)$/i.test(t));
  const already = /Candidatura enviada|Aplicada/i.test(pageText.slice(0, 4000));
  const closed = /não está mais aceitando|no longer accepting|Vaga encerrada|Esta vaga foi encerrada/i.test(pageText);
  return JSON.stringify({
    url: location.href,
    title, company,
    location_line: (primary + ' | ' + tertiary).replace(/\s*\|\s*$/, ''),
    workplace: wpType,
    apply_labels: [...new Set(applyLabels)],
    already_applied: already,
    closed,
    desc_len: desc.length,
    desc: desc.slice(0, 9000),
  });
})()
