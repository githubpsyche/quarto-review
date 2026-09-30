-- Keep review markers out of CSL affixes. Restore them after citation formatting.
local M = {}
local pattern = "QRX[CIDFO]Q[0-9A-F]+Q[SE]XQR"

function M.protect(markdown)
  -- A code inline delimits @key and [@key] while retaining heading-ID input.
  -- An empty span would be mistaken for a link suffix in the latter case.
  return markdown:gsub(pattern, function(token)
    return '`' .. token .. '`{.quarto-review-marker}'
  end)
end

function M.prepare(doc)
  local plans, deferred = {}, {}
  -- Pandoc duplicates visible figure captions into image alternatives. Only
  -- the visible caption owns review boundaries and a citation recovery plan.
  doc = doc:walk({Figure = function(figure)
    figure.content = pandoc.Div(figure.content):walk({Image = function(image)
      local function strip(node)
        if node.classes:includes('quarto-review-marker') then return {} end
      end
      image.caption = pandoc.Span(image.caption):walk({
        Code = strip,
        Cite = function(cite)
          for _, citation in ipairs(cite.citations) do
            citation.prefix = citation.prefix:walk({Code = strip})
            citation.suffix = citation.suffix:walk({Code = strip})
          end
          return cite
        end
      }).content
      return image
    end}).content
    return figure
  end})
  doc = doc:walk({Cite = function(cite)
    local marks, keys, prefixes, suffixes = {}, {}, {}, {}
    local function affix(inlines, index, side)
      local text = pandoc.utils.stringify(pandoc.Span(inlines):walk({Code = function(node)
        if node.classes:includes('quarto-review-marker') then return pandoc.Str(node.text) end
      end}))
      for position, token in text:gmatch('()(' .. pattern .. ')') do
        table.insert(marks, {token=token, index=index, side=side,
          before=text:sub(1, position - 1):gsub(pattern, ''), text=text:gsub(pattern, '')})
        deferred[token] = (deferred[token] or 0) + 1
      end
      if not text:find(pattern) then return inlines end
      local cleaned = inlines:walk({Code = function(node)
        if node.classes:includes('quarto-review-marker') then return {} end
      end})
      while #cleaned > 0 and (cleaned[1].t == 'Space' or cleaned[1].t == 'SoftBreak') do cleaned:remove(1) end
      while #cleaned > 0 and (cleaned[#cleaned].t == 'Space' or cleaned[#cleaned].t == 'SoftBreak') do cleaned:remove(#cleaned) end
      return cleaned
    end
    for index, citation in ipairs(cite.citations) do
      table.insert(keys, citation.id)
      citation.prefix = affix(citation.prefix, index, 'prefix')
      citation.suffix = affix(citation.suffix, index, 'suffix')
      table.insert(prefixes, pandoc.utils.stringify(citation.prefix))
      table.insert(suffixes, pandoc.utils.stringify(citation.suffix))
    end
    if #marks == 0 then return cite end
    for _, citation in ipairs(cite.citations) do
      if citation.mode == 'AuthorInText' then
        error('Review boundaries inside narrative citations are not supported; anchor the whole narrative citation instead')
      end
    end
    if doc.meta['link-citations'] == false then
      error('Review inside citation groups requires link-citations: true to retain citation identities during formatting')
    end
    doc.meta['link-citations'] = true
    local id = 'qr_cite_' .. (#plans + 1)
    table.insert(plans, {id=id, keys=keys, prefixes=prefixes, suffixes=suffixes, markers=marks})
    -- Cite content is the unformatted source spelling, not its semantic input.
    -- Never let a marker duplicated there reach the ordinary boundary walker.
    cite.content = {pandoc.Str('[@' .. table.concat(keys, '; @') .. ']')}
    return pandoc.Span({cite}, pandoc.Attr(id, {'qr-citation'}))
  end})
  doc = doc:walk({Code = function(node)
    if node.classes:includes('quarto-review-marker') then return pandoc.Str(node.text) end
  end})
  return doc, plans, deferred
end

return M
