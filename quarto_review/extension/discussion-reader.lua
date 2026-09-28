-- Parse each message independently; references and unclosed fences cannot leak
-- between threads. This reader never runs Quarto execution or manuscript filters.
function Reader(input)
  local blocks = pandoc.List()
  for index, body in ipairs(pandoc.json.decode(tostring(input))) do
    local message = pandoc.read(body, "commonmark"):walk({
      RawInline = function(node) return pandoc.Str(node.text) end,
      RawBlock = function(node) return pandoc.Para({pandoc.Str(node.text)}) end,
      CodeBlock = function(node)
        -- Plain code avoids generated syntax-highlighting IDs and jump links.
        node.attr = pandoc.Attr()
        return node
      end
    })
    blocks:insert(pandoc.Div(message.blocks, pandoc.Attr("message-" .. index, {"qr-message"})))
  end
  return pandoc.Pandoc(blocks)
end
