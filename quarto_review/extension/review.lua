-- Review preparation uses the executed Markdown, before Quarto normalizes its AST.
local readqmd = require("readqmd")
local citation_boundaries = dofile(pandoc.path.directory(PANDOC_SCRIPT_FILE) .. "/citation-boundaries.lua")

local function read_file(path)
  local stream, reason = io.open(path, "r")
  if not stream then error("Quarto review cannot read its intermediate input: " .. reason) end
  local source = stream:read("*a")
  stream:close()
  return source
end

local function html_boundaries(doc, expected)
  local found = {}
  local function convert(element)
    local output = pandoc.Inlines({})
    local cursor = 1
    while true do
      local first, last, kind, encoded, edge = element.text:find("QRX([CIDFO])Q([0-9A-F]+)Q([SE])XQR", cursor)
      if not first then
        if cursor <= #element.text then output:insert(pandoc.Str(element.text:sub(cursor))) end
        break
      end
      if first > cursor then output:insert(pandoc.Str(element.text:sub(cursor, first - 1))) end
      local token = element.text:sub(first, last)
      found[token] = (found[token] or 0) + 1
      local id = encoded:gsub("..", function(byte) return string.char(tonumber(byte, 16)) end)
      output:insert(pandoc.RawInline("html", '<span class="qr-boundary" data-review-kind="' .. kind .. '" data-review-id="' .. id .. '" data-review-edge="' .. edge .. '"></span>'))
      cursor = last + 1
    end
    return output
  end
  -- Pandoc copies a figure caption into its image alt text. Only the visible
  -- caption owns review ranges; leaving the copy makes one source range count
  -- twice and exposes internal markers in accessibility text.
  doc = doc:walk({Figure = function(figure)
    local caption_tokens = {}
    pandoc.Div(figure.caption.long):walk({Str = function(element)
      for token in element.text:gmatch("QRX[CIDFO]Q[0-9A-F]+Q[SE]XQR") do
        caption_tokens[token] = true
      end
    end})
    figure.content = pandoc.Div(figure.content):walk({Image = function(element)
      element.caption = pandoc.Span(element.caption):walk({Str = function(part)
        part.text = part.text:gsub("QRX[CIDFO]Q[0-9A-F]+Q[SE]XQR", function(token)
          return caption_tokens[token] and "" or token
        end)
        return part
      end}).content
      return element
    end}).content
    return figure
  end})
  doc = doc:walk({Str = convert})
  for token, count in pairs(expected) do
    if found[token] ~= count then error("HTML conversion changed review boundary " .. token) end
  end
  for token, count in pairs(found) do
    if expected[token] ~= count then error("HTML conversion duplicated review boundary " .. token) end
  end
  -- The Markdown reader makes automatic heading identifiers before review
  -- markers become HTML spans. Remove those markers from identifiers too,
  -- retaining explicit IDs and preventing collisions with existing anchors.
  local marker_pattern = "qrx[cidfo]q[0-9a-f]+q[se]xqr"
  local occupied, renamed = {}, {}
  local function reserve(element)
    local id = element.identifier
    if id and id ~= "" and not id:find(marker_pattern) then occupied[id] = true end
  end
  doc:walk({Header = reserve, Div = reserve, Span = reserve,
    CodeBlock = reserve, Code = reserve, Link = reserve, Image = reserve,
    Table = reserve, Figure = reserve})
  doc = doc:walk({Header = function(header)
    local old = header.identifier
    if not old:find(marker_pattern) then return nil end
    local base = old:gsub(marker_pattern, ""):gsub("%-+", "-"):gsub("^%-", ""):gsub("%-$", "")
    if base == "" then base = "section" end
    local id, suffix = base, 1
    while occupied[id] do
      id = base .. "-" .. suffix
      suffix = suffix + 1
    end
    occupied[id] = true
    renamed[old] = id
    header.identifier = id
    return header
  end})
  doc = doc:walk({Link = function(link)
    local target = link.target:match("^#(.+)$")
    if target and renamed[target] then
      link.target = "#" .. renamed[target]
      return link
    end
  end})
  return doc
end

function Pandoc(doc)
  local started = os.clock()
  local function timing(stage)
    if os.getenv("QUARTO_REVIEW_TIMING") then
      io.stderr:write(string.format("Quarto review %s: %.3fs CPU\n", stage, os.clock() - started))
    end
  end
  if os.getenv("QUARTO_REVIEW_TIMING") then
    io.stderr:write(string.format("Quarto review entered filter: %.3fs total CPU\n", started))
  end
  local directory = quarto.project.directory
  if not directory then error("Quarto review requires an enabled review project") end
  local input = PANDOC_STATE.input_files[1]
  if not input then error("Quarto review cannot locate the executed Markdown input") end
  local command = os.getenv("QUARTO_REVIEW_COMMAND") or "quarto-review"
  local format = quarto.doc.is_format("docx") and "docx"
    or (quarto.doc.is_format("html") and "html" or "clean")
  local encoded = pandoc.pipe(command, {
    "prepare", "--project", directory, "--source", quarto.doc.input_file,
    "--output", quarto.doc.output_file, "--format", format
  }, read_file(input))
  timing("prepared source")
  local payload = quarto.json.decode(encoded)
  timing("decoded records")
  local options
  if doc.meta.quarto_pandoc_reader_opts then
    options = readqmd.meta_to_options(doc.meta.quarto_pandoc_reader_opts)
  elseif quarto_global_state and quarto_global_state.reader_options then
    options = quarto_global_state.reader_options
  else
    error("This Quarto version does not expose the reader options required by Quarto review")
  end
  local extensions = {}
  for _, extension in ipairs(options.extensions) do
    if extension ~= "smart" then table.insert(extensions, extension) end
  end
  options.extensions = extensions
  local parsed = readqmd.readqmd(citation_boundaries.protect(payload.markdown), options)
  timing("parsed Markdown")
  doc.blocks = parsed.blocks
  timing("assigned blocks")
  for key, value in pairs(parsed.meta) do doc.meta[key] = value end
  local citation_plans, deferred
  doc, citation_plans, deferred = citation_boundaries.prepare(doc)
  if payload.citation_plan then
    local file, reason = io.open(directory .. "/" .. payload.citation_plan, "w")
    if not file then error("Cannot save citation boundary plan: " .. reason) end
    file:write(quarto.json.encode(citation_plans))
    file:close()
  end
  if format == "html" then
    local immediate = {}
    for token, count in pairs(payload.expected) do
      local remaining = count - (deferred[token] or 0)
      if remaining > 0 then immediate[token] = remaining end
    end
    doc = html_boundaries(doc, immediate)
    doc.blocks:insert(pandoc.RawBlock("html", payload.panel))
    quarto.doc.add_html_dependency({name = "quarto-review", version = "0.3.1", scripts = {"review.js"}, stylesheets = {"review.css"}})
  end
  timing("complete")
  return doc
end
