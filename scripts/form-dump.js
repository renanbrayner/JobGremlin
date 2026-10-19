(() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const limpar = s => norm(s).replace(/\d+\s*\/\s*\d+/g, '').replace(/\d+ de \d+ caracteres?/gi, '').trim();
  const out = { pagina: '', grupos: [], inputs: [], selects: [], checks: [] };
  const m = (document.body.innerText || '').match(/(\d+)\s*de\s*(\d+)\s*p[áa]ginas/i);
  if (m) out.pagina = m[1] + '/' + m[2];
  // radios agrupados pelo name
  const nomes = [...new Set([...document.querySelectorAll('input[type=radio]')].map(r => r.name).filter(Boolean))];
  for (const n of nomes) {
    const rs = [...document.querySelectorAll('input[type=radio]')].filter(r => r.name === n);
    const r0 = rs[0];
    const avo = r0.parentElement && r0.parentElement.parentElement;
    let perg = limpar((r0.getAttribute('aria-label') || '')) ;
    if (!perg && avo) perg = limpar(avo.innerText).slice(0, 220);
    const opcoes = rs.map(r => {
      const p = r.parentElement, a = p && p.parentElement;
      return { txt: limpar((a && a.innerText) || (p && p.innerText) || r.value).slice(0, 60), checked: r.checked };
    });
    out.grupos.push({ pergunta: perg, opcoes });
  }
  for (const i of document.querySelectorAll('input[type=text],input[type=number],textarea')) {
    const pai = i.closest('div');
    out.inputs.push({ tipo: i.tagName.toLowerCase(), valor: (i.value || '').slice(0, 40), label: limpar(i.getAttribute('aria-label') || (pai && pai.innerText) || '').slice(0, 160) });
  }
  for (const s of document.querySelectorAll('select')) {
    out.selects.push({ opcoes: [...s.options].map(o => o.text).slice(0, 8), valor: s.value, label: limpar(s.getAttribute('aria-label') || '').slice(0, 140) });
  }
  for (const c of document.querySelectorAll('input[type=checkbox]')) {
    const pai = c.parentElement && c.parentElement.parentElement;
    out.checks.push({ marcado: c.checked, label: limpar((pai && pai.innerText) || '').slice(0, 120) });
  }
  return JSON.stringify(out, null, 1);
})()
