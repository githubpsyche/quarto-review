-- Run after Quarto has resolved cross-references and presentation metadata.
-- CSL still owns citation formatting; reviewed source bibliography is opt-in.
function Pandoc(doc)
  local has_ranges = false
  doc:walk({Span = function(span)
    if span.classes:includes('qr-citation') then has_ranges = true end
  end})
  if has_ranges then
    if doc.meta['link-citations'] == false then
      error('Review inside citation groups requires link-citations: true')
    end
    doc.meta['link-citations'] = true
  end
  local settings = doc.meta['quarto-review']
  if not settings or not settings.bibliography then return doc end
  local mode = pandoc.utils.stringify(settings.bibliography)
  if mode == 'generated' then return doc end
  if mode ~= 'source' then
    error('quarto-review.bibliography must be generated or source')
  end
  local retained, count = nil, 0
  doc = doc:walk({Div = function(div)
    if div.identifier == 'refs' then
      count = count + 1
      retained = div
      return pandoc.Div({}, pandoc.Attr('qr-source-bibliography'))
    end
  end})
  if count ~= 1 then
    error('Source bibliography mode requires exactly one explicit ::: {#refs} block')
  end
  if doc.meta['suppress-bibliography'] == true then
    error('Source bibliography mode needs citation links; remove suppress-bibliography')
  end
  doc = pandoc.utils.citeproc(doc)
  doc = doc:walk({
    Div = function(div)
      if div.identifier == 'refs' then return {} end
      if div.identifier == 'qr-source-bibliography' then return retained end
    end,
    -- Keep formatted output; a later Quarto citeproc pass must not run twice.
    Cite = function(cite) return cite.content end
  })
  doc.meta.bibliography = nil
  doc.meta.references = nil
  return doc
end
